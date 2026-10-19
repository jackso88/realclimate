"""Tests for the reference downloader's failure path, producer and entrypoints."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
import requests

from app.downloader.reference import auth_cli, consumer, producer
from app.downloader.reference.config import SCOPES
from app.downloader.reference.exceptions import ReferenceAuthenticationError
from app.contracts.models import Envelope
from app.messaging.payloads import decode_bytes
from app.messaging.exceptions import RetryableMessageError
from app.messaging.topics import (
    REFERENCE_DOWNLOADS,
    REFERENCE_PIPELINE_COMPLETED,
    REFERENCE_SNAPSHOT_STATE,
    REFERENCE_SYNC_REQUESTS,
)

SETTINGS = SimpleNamespace(
    spreadsheet_url="https://docs.google.com/spreadsheets/d/SHEET123/edit",
    sheet_name="1. Для заливки",
    credentials_file="credentials.json",
    token_file="token.json",
    bootstrap_servers="localhost:9092",
)


def make_request():
    return Envelope.create("sync_reference", {}, correlation_id="r-1")


@pytest.fixture
def sheet(monkeypatch):
    """Mock the Google client chain and the reply helpers used by the handler."""
    parts = SimpleNamespace(
        worksheet=Mock(),
        spreadsheet=Mock(),
        client=Mock(),
        failure=Mock(),
        publish=Mock(return_value=True),
        checkpoint=Mock(),
        credentials=Mock(return_value="credentials"),
    )
    parts.worksheet.get_all_values.return_value = [["код", "модель"], ["НС-1", "A"]]
    parts.spreadsheet.worksheet.return_value = parts.worksheet
    parts.client.open_by_key.return_value = parts.spreadsheet
    monkeypatch.setattr(consumer, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(consumer, "get_credentials", parts.credentials)
    monkeypatch.setattr(consumer.gspread, "authorize", Mock(return_value=parts.client))
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    monkeypatch.setattr(consumer, "publish_reference_if_changed", parts.publish)
    monkeypatch.setattr(consumer, "checkpoint_completed_reference", parts.checkpoint)
    return parts


def test_handler_reads_the_configured_worksheet_and_publishes_changed_snapshot(sheet):
    bus = object()
    request = make_request()

    consumer.handle_request(request, bus)

    sheet.client.open_by_key.assert_called_once_with("SHEET123")
    sheet.spreadsheet.worksheet.assert_called_once_with("1. Для заливки")
    sheet.credentials.assert_called_once_with("credentials.json", "token.json", SCOPES)
    published = sheet.publish.call_args.args
    assert published[:2] == (bus, request)
    assert "НС-1".encode("utf-8") in published[2]
    sheet.failure.assert_not_called()


def test_handler_uses_service_account_when_configured(sheet, monkeypatch):
    service_account_settings = SimpleNamespace(
        **{
            **vars(SETTINGS),
            "auth_mode": "service_account",
            "service_account_file": "/credentials/service_account_secret.json",
        }
    )
    service_credentials = Mock(return_value="service credentials")
    monkeypatch.setattr(consumer, "load_settings", lambda: service_account_settings)
    monkeypatch.setattr(
        consumer, "get_service_account_credentials", service_credentials
    )

    consumer.handle_request(make_request(), object())

    service_credentials.assert_called_once_with(
        "/credentials/service_account_secret.json", SCOPES
    )
    sheet.credentials.assert_not_called()


def test_service_account_permission_denial_retries_with_cached_user_oauth(
    sheet, monkeypatch, tmp_path
):
    user_credentials_file = tmp_path / "client_secret.json"
    user_credentials_file.write_text("{}", encoding="utf-8")
    user_token_file = tmp_path / "token.json"
    user_token_file.write_text("{}", encoding="utf-8")
    service_account_settings = SimpleNamespace(
        **{
            **vars(SETTINGS),
            "auth_mode": "service_account",
            "service_account_file": tmp_path / "service_account_secret.json",
            "credentials_file": user_credentials_file,
            "token_file": user_token_file,
        }
    )
    service_client = Mock()
    service_client.open_by_key.side_effect = PermissionError
    service_credentials = Mock(return_value="service credentials")
    user_credentials = Mock(return_value="user credentials")
    authorize = Mock(side_effect=[service_client, sheet.client])
    monkeypatch.setattr(consumer, "load_settings", lambda: service_account_settings)
    monkeypatch.setattr(
        consumer, "get_service_account_credentials", service_credentials
    )
    monkeypatch.setattr(consumer, "get_credentials", user_credentials)
    monkeypatch.setattr(consumer.gspread, "authorize", authorize)

    request = make_request()
    consumer.handle_request(request, object())

    service_client.open_by_key.assert_called_once_with("SHEET123")
    user_credentials.assert_called_once_with(
        user_credentials_file, user_token_file, SCOPES
    )
    assert authorize.call_args_list == [
        call(service_credentials.return_value),
        call(user_credentials.return_value),
    ]
    assert sheet.publish.called
    sheet.failure.assert_not_called()


def test_google_failure_is_published_as_a_failure_event(sheet):
    sheet.worksheet.get_all_values.side_effect = RuntimeError("quota exceeded")
    bus = object()
    request = make_request()

    consumer.handle_request(request, bus)

    sheet.failure.assert_called_once()
    assert str(sheet.failure.call_args.args[2]) == "quota exceeded"
    sheet.publish.assert_not_called()


def test_transient_google_timeout_is_reported_and_left_for_retry(sheet):
    sheet.worksheet.get_all_values.side_effect = requests.Timeout("Google timed out")

    with pytest.raises(RetryableMessageError, match="Transient failure"):
        consumer.handle_request(make_request(), object())

    sheet.failure.assert_called_once()
    sheet.publish.assert_not_called()


def test_authentication_failure_is_published_as_a_failure_event(sheet):
    error = ReferenceAuthenticationError("Google OAuth authorization failed")
    sheet.credentials.side_effect = error
    bus = object()
    request = make_request()

    consumer.handle_request(request, bus)

    sheet.failure.assert_called_once()
    assert str(sheet.failure.call_args.args[2]) == "Google OAuth authorization failed"


def test_invalid_spreadsheet_url_is_returned_as_an_error_reply(sheet, monkeypatch):
    broken = SimpleNamespace(**{**vars(SETTINGS), "spreadsheet_url": "not a sheet url"})
    monkeypatch.setattr(consumer, "load_settings", lambda: broken)

    consumer.handle_request(make_request(), object())

    assert "spreadsheet ID" in str(sheet.failure.call_args.args[2])
    sheet.credentials.assert_not_called()


def test_unexpected_command_is_reported_without_google_access(sheet):
    request = Envelope.create("unsupported", {}, correlation_id="bad-ref-event")

    consumer.handle_request(request, object())

    assert "Unsupported reference command" in str(sheet.failure.call_args.args[2])
    assert sheet.failure.call_args.args[3] == "bad-ref-event"
    sheet.credentials.assert_not_called()


def test_main_runs_the_reference_downloader_worker(monkeypatch):
    run_consumer = Mock()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", lambda: SETTINGS)

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == (
        "localhost:9092",
        [REFERENCE_SYNC_REQUESTS, REFERENCE_PIPELINE_COMPLETED],
        "reference-downloader-service",
    )
    assert args[3].func is consumer.handle_request
    assert args[3].keywords == {"settings": SETTINGS}
    assert kwargs == {"service_name": "downloader_reference"}


def test_publisher_skips_identical_reference_bytes():
    bus = Mock()
    digest = hashlib.sha256(b"same bytes").hexdigest()
    previous = Envelope.create("reference_snapshot_state", {"sha256": digest})
    bus.read_latest.return_value = previous
    request = make_request()

    changed = producer.publish_reference_if_changed(bus, request, b"same bytes")

    assert changed is False
    bus.publish.assert_not_called()


def test_publisher_emits_changed_snapshot_and_advances_state():
    bus = Mock()
    bus.read_latest.return_value = None
    request = make_request()

    changed = producer.publish_reference_if_changed(bus, request, b"new bytes")

    assert changed is True
    bus.publish.assert_called_once()
    assert bus.publish.call_args.args[0] == REFERENCE_DOWNLOADS
    snapshot_event = bus.publish.call_args.args[1]
    assert snapshot_event.correlation_id == request.correlation_id
    assert (
        decode_bytes(snapshot_event.payload["reference_csv_gzip_base64"])
        == b"new bytes"
    )
    bus.read_latest.assert_called_once_with(REFERENCE_SNAPSHOT_STATE)


def test_checkpoint_persists_the_digest_after_pipeline_completion():
    bus = Mock()
    completion = Envelope.create(
        "pipeline_completed",
        {"reference_sha256": "digest"},
        correlation_id="completed-run",
    )

    producer.checkpoint_completed_reference(bus, completion)

    bus.publish.assert_called_once()
    topic, state = bus.publish.call_args.args
    assert topic == REFERENCE_SNAPSHOT_STATE
    assert bus.publish.call_args.kwargs == {"key": "reference-snapshot"}
    assert state.payload == {"sha256": "digest"}
    assert state.correlation_id == "completed-run"


def test_pipeline_completion_is_checkpointed_without_loading_google_credentials(
    sheet,
):
    bus = object()
    completion = Envelope.create(
        "pipeline_completed",
        {"reference_sha256": "digest"},
        correlation_id="completed-run",
    )

    consumer.handle_request(completion, bus)

    sheet.checkpoint.assert_called_once_with(bus, completion)
    sheet.credentials.assert_not_called()
    sheet.publish.assert_not_called()


def test_auth_cli_runs_the_oauth_flow_once_for_the_configured_files(monkeypatch):
    get_credentials = Mock()
    configure = Mock()
    monkeypatch.setattr(auth_cli, "configure_logging", configure)
    monkeypatch.setattr(auth_cli, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(auth_cli, "get_credentials", get_credentials)

    auth_cli.main()

    configure.assert_called_once_with()
    get_credentials.assert_called_once_with("credentials.json", "token.json", SCOPES)

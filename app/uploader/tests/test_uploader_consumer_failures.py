"""Tests for uploader failures and consumer wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.contracts.models import Envelope
from app.messaging.payloads import encode_bytes
from app.uploader import consumer
from app.uploader.exceptions import ImportQueueError


@pytest.fixture
def steps(monkeypatch):
    """Mock every CMS step and the service failure publisher."""
    parts = SimpleNamespace(failure=Mock(), delete=Mock(), upload=Mock(), wait=Mock())
    monkeypatch.setattr(consumer, "load_settings", lambda: "settings")
    monkeypatch.setattr(consumer, "request_session", Mock(return_value="session"))
    monkeypatch.setattr(consumer, "upload_processed_content", parts.upload)
    monkeypatch.setattr(consumer, "get_latest_import_cron_num", Mock(return_value=1))
    monkeypatch.setattr(consumer, "start_product_import", Mock())
    monkeypatch.setattr(consumer, "wait_for_import_completion", parts.wait)
    monkeypatch.setattr(consumer, "delete_uploaded_file", parts.delete)
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    return parts


def make_result(**payload):
    payload.setdefault("detailed_changes", ["price changed"])
    payload.setdefault("processed_csv_gzip_base64", encode_bytes(b"csv"))
    return Envelope.create("catalogue_processed", payload, correlation_id="pipeline-1")


def test_failed_import_is_reported_as_a_service_failure(steps):
    steps.wait.side_effect = ImportQueueError("Import task #9 failed")
    bus = object()

    consumer.handle_processed_catalogue(make_result(), bus)

    steps.failure.assert_called_once()
    assert steps.failure.call_args.args[1] == "uploader"
    assert str(steps.failure.call_args.args[2]) == "Import task #9 failed"
    assert steps.failure.call_args.args[3] == "pipeline-1"
    steps.delete.assert_not_called()


def test_failed_upload_stops_before_import_and_notifies(steps):
    steps.upload.side_effect = RuntimeError("CMS unreachable")
    bus = object()

    consumer.handle_processed_catalogue(make_result(), bus)

    assert str(steps.failure.call_args.args[2]) == "CMS unreachable"
    steps.wait.assert_not_called()


def test_missing_processed_payload_is_reported(steps):
    message = Envelope.create(
        "catalogue_processed", {"detailed_changes": ["changed"]}, correlation_id="x"
    )

    consumer.handle_processed_catalogue(message, object())

    assert "processed_csv_gzip_base64" in str(steps.failure.call_args.args[2])
    steps.upload.assert_not_called()


def test_unexpected_core_event_is_reported_without_upload(steps):
    message = Envelope.create("wrong_command", {}, correlation_id="bad-result")

    consumer.handle_processed_catalogue(message, object())

    assert "Unsupported uploader command" in str(steps.failure.call_args.args[2])
    assert steps.failure.call_args.args[3] == "bad-result"
    steps.upload.assert_not_called()


def test_filename_is_fixed_to_the_processed_export(steps):
    steps.upload.return_value = type("File", (), {"file_id": "id"})()
    steps.wait.return_value = type("Task", (), {"cron_num": 2})()

    consumer.handle_processed_catalogue(make_result(), object())

    assert steps.upload.call_args.args[3] == "processed.csv"

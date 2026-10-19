"""Tests for the uploader worker's failure path and process wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import UPLOADER_REQUESTS
from app.uploader import consumer
from app.uploader.exceptions import ImportQueueError


@pytest.fixture
def steps(monkeypatch):
    """Mock every CMS step so a test can make exactly one of them fail."""
    parts = type("Steps", (), {})()
    parts.reply = Mock()
    parts.delete = Mock()
    parts.upload = Mock()
    parts.wait = Mock()
    monkeypatch.setattr(consumer, "load_settings", lambda: "settings")
    monkeypatch.setattr(consumer, "request_session", Mock(return_value="session"))
    monkeypatch.setattr(consumer, "upload_processed_content", parts.upload)
    monkeypatch.setattr(consumer, "get_latest_import_cron_num", Mock(return_value=1))
    monkeypatch.setattr(consumer, "start_product_import", Mock())
    monkeypatch.setattr(consumer, "wait_for_import_completion", parts.wait)
    monkeypatch.setattr(consumer, "delete_uploaded_file", parts.delete)
    monkeypatch.setattr(consumer, "publish_reply", parts.reply)
    return parts


def make_request(**payload):
    payload.setdefault("csv_gzip_base64", encode_bytes(b"csv"))
    return Envelope.create("import_processed_csv", payload, reply_to="responses")


def test_failed_import_is_reported_to_the_requester(steps):
    steps.wait.side_effect = ImportQueueError("Import task #9 failed")
    bus = object()
    request = make_request()

    consumer.handle_request(request, bus)

    steps.reply.assert_called_once_with(bus, request, error="Import task #9 failed")
    steps.delete.assert_not_called()


def test_failed_upload_stops_before_any_import_is_started(steps):
    steps.upload.side_effect = RuntimeError("CMS unreachable")

    consumer.handle_request(make_request(), object())

    assert steps.reply.call_args.kwargs == {"error": "CMS unreachable"}
    steps.wait.assert_not_called()


def test_request_without_a_payload_is_answered_with_an_error(steps):
    request = Envelope.create("import_processed_csv", {}, reply_to="responses")

    consumer.handle_request(request, object())

    assert "csv_gzip_base64" in steps.reply.call_args.kwargs["error"]
    steps.upload.assert_not_called()


def test_filename_defaults_to_processed_csv(steps):
    steps.upload.return_value = type("File", (), {"file_id": "1"})()
    steps.wait.return_value = type("Task", (), {"cron_num": 2})()

    consumer.handle_request(make_request(), object())

    assert steps.upload.call_args.args[3] == "processed.csv"


def test_main_runs_the_uploader_worker(monkeypatch):
    run_consumer = Mock()
    settings = SimpleNamespace(bootstrap_servers="localhost:9092")
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(
        consumer,
        "load_settings",
        lambda: settings,
    )

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == ("localhost:9092", UPLOADER_REQUESTS, "uploader-service")
    assert args[3].func is consumer.handle_request
    assert args[3].keywords == {"settings": settings}
    assert kwargs == {"service_name": "uploader"}

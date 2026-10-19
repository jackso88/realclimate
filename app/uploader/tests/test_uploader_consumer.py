"""Tests for uploader subscription to core result events."""

from unittest.mock import Mock

import pytest

from app.contracts.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import CORE_PROCESS_RESULTS, REFERENCE_PIPELINE_COMPLETED
from app.uploader import consumer
from app.uploader.models import ImportQueueItem, UploadedFile


@pytest.fixture(autouse=True)
def bypass_rate_limit_setup(monkeypatch):
    """Keep consumer contract tests independent of Kafka infrastructure."""
    monkeypatch.setattr(consumer, "rate_limit_session", lambda session, *_: session)


def test_uploader_imports_processed_csv_and_preserves_pipeline_id(monkeypatch):
    settings = object()
    session = object()
    uploaded = UploadedFile(file_id="fake-file-id", filename="processed.csv")
    completed = ImportQueueItem(cron_num=42, status="Готово")
    content = b"processed csv bytes"
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "request_session", Mock(return_value=session))
    upload = Mock(return_value=uploaded)
    monkeypatch.setattr(consumer, "upload_processed_content", upload)
    monkeypatch.setattr(consumer, "get_latest_import_cron_num", Mock(return_value=41))
    monkeypatch.setattr(consumer, "start_product_import", Mock())
    wait = Mock(return_value=completed)
    monkeypatch.setattr(consumer, "wait_for_import_completion", wait)
    delete = Mock()
    monkeypatch.setattr(consumer, "delete_uploaded_file", delete)
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_failure", failure)
    message = Envelope.create(
        "catalogue_processed",
        {
            "reference_sha256": "fake-digest",
            "detailed_changes": ["price changed"],
            "processed_csv_gzip_base64": encode_bytes(content),
        },
        correlation_id="pipeline-42",
    )
    bus = Mock()

    consumer.handle_processed_catalogue(message, bus)

    upload.assert_called_once_with(session, settings, content, "processed.csv")
    consumer.start_product_import.assert_called_once_with(session, settings, uploaded)
    wait.assert_called_once_with(session, settings, 41)
    delete.assert_called_once_with(session, settings, uploaded)
    bus.publish.assert_called_once()
    topic, completion = bus.publish.call_args.args
    assert topic == REFERENCE_PIPELINE_COMPLETED
    assert completion.payload == {"reference_sha256": "fake-digest"}
    assert completion.correlation_id == "pipeline-42"
    failure.assert_not_called()


def test_no_detailed_changes_skip_admin_auth_and_upload(monkeypatch):
    session = Mock()
    monkeypatch.setattr(consumer, "request_session", session)
    upload = Mock()
    monkeypatch.setattr(consumer, "upload_processed_content", upload)
    message = Envelope.create(
        "catalogue_processed", {"detailed_changes": []}, correlation_id="unchanged"
    )

    consumer.handle_processed_catalogue(message, object())

    session.assert_not_called()
    upload.assert_not_called()


def test_worker_subscribes_to_core_result_events(monkeypatch):
    run_consumer = Mock()
    settings = type("Settings", (), {"bootstrap_servers": "broker:9092"})()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == ("broker:9092", CORE_PROCESS_RESULTS, "uploader-service")
    assert args[3].func is consumer.handle_processed_catalogue
    assert args[3].keywords == {"settings": settings}
    assert kwargs == {"service_name": "uploader"}

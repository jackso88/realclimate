"""Tests for uploader failures and consumer wiring."""

import pytest
import requests

from app.contracts.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.exceptions import RetryableMessageError
from app.uploader import consumer
from app.uploader.exceptions import ImportQueueError

pytestmark = pytest.mark.usefixtures("uploader_bypass_rate_limit")


def make_result(**payload):
    payload.setdefault("detailed_changes", ["price changed"])
    payload.setdefault("processed_csv_gzip_base64", encode_bytes(b"csv"))
    return Envelope.create("catalogue_processed", payload, correlation_id="pipeline-1")


def test_failed_import_is_reported_as_a_service_failure(uploader_steps):
    uploader_steps.wait.side_effect = ImportQueueError("Import task #9 failed")
    bus = object()

    consumer.handle_processed_catalogue(make_result(), bus)

    uploader_steps.failure.assert_called_once()
    assert uploader_steps.failure.call_args.args[1] == "uploader"
    assert str(uploader_steps.failure.call_args.args[2]) == "Import task #9 failed"
    assert uploader_steps.failure.call_args.args[3] == "pipeline-1"
    uploader_steps.delete.assert_called_once()


def test_failed_upload_stops_before_import_and_notifies(uploader_steps):
    uploader_steps.upload.side_effect = RuntimeError("CMS unreachable")
    bus = object()

    consumer.handle_processed_catalogue(make_result(), bus)

    assert str(uploader_steps.failure.call_args.args[2]) == "CMS unreachable"
    uploader_steps.wait.assert_not_called()


def test_transient_cms_error_is_reported_and_left_for_retry(uploader_steps):
    uploaded_file = type("File", (), {"file_id": "opaque-id"})()
    uploader_steps.upload.return_value = uploaded_file
    uploader_steps.start_import.side_effect = requests.Timeout("CMS timed out")

    with pytest.raises(RetryableMessageError, match="Transient failure"):
        consumer.handle_processed_catalogue(make_result(), object())

    uploader_steps.delete.assert_called_once_with("session", "settings", uploaded_file)
    uploader_steps.failure.assert_called_once()


def test_missing_processed_payload_is_reported(uploader_steps):
    message = Envelope.create(
        "catalogue_processed", {"detailed_changes": ["changed"]}, correlation_id="x"
    )

    consumer.handle_processed_catalogue(message, object())

    assert "processed_csv_gzip_base64" in str(uploader_steps.failure.call_args.args[2])
    uploader_steps.upload.assert_not_called()


def test_unexpected_core_event_is_reported_without_upload(uploader_steps):
    message = Envelope.create("wrong_command", {}, correlation_id="bad-result")

    consumer.handle_processed_catalogue(message, object())

    assert "Unsupported uploader command" in str(
        uploader_steps.failure.call_args.args[2]
    )
    assert uploader_steps.failure.call_args.args[3] == "bad-result"
    uploader_steps.upload.assert_not_called()


def test_filename_is_fixed_to_the_processed_export(uploader_steps):
    uploader_steps.upload.return_value = type("File", (), {"file_id": "id"})()
    uploader_steps.wait.return_value = type("Task", (), {"cron_num": 2})()

    consumer.handle_processed_catalogue(make_result(), object())

    assert uploader_steps.upload.call_args.args[3] == "processed.csv"

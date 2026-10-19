"""Tests for the uploader request/reply contract."""

from unittest.mock import Mock

from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.uploader import consumer
from app.uploader.models import ImportQueueItem, UploadedFile


def test_uploader_imports_supplied_processed_csv(monkeypatch):
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
    monkeypatch.setattr(consumer, "delete_uploaded_file", Mock())
    publish = Mock()
    monkeypatch.setattr(consumer, "publish_reply", publish)
    monkeypatch.setattr(consumer, "decode_bytes", lambda _: content)
    request = Envelope.create(
        "import_processed_csv",
        {"csv_gzip_base64": encode_bytes(content), "filename": "processed.csv"},
        reply_to="response",
    )
    bus = object()

    consumer.handle_request(request, bus)

    upload.assert_called_once_with(session, settings, content, "processed.csv")
    consumer.start_product_import.assert_called_once_with(session, settings, uploaded)
    wait.assert_called_once_with(session, settings, 41)
    consumer.delete_uploaded_file.assert_called_once_with(session, settings, uploaded)
    publish.assert_called_once_with(
        bus, request, {"cron_num": 42, "file_id": "fake-file-id"}
    )

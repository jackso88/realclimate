"""Focused tests for the current downloader's pub/sub consumer contract."""

from unittest.mock import Mock

from app.contracts.models import Envelope
from app.downloader.current import consumer
from app.downloader.current.models import DownloadedCsv


def test_reference_completion_triggers_and_publishes_current_csv(monkeypatch):
    settings = object()
    session = object()
    bus = object()
    message = Envelope.create(
        "reference_downloaded",
        {"reference_sha256": "reference-digest"},
        correlation_id="pipeline-123",
    )
    downloaded = DownloadedCsv(
        cron_num=12,
        filename="export.csv",
        content=b"current csv",
        archive_filename="archive.zip",
    )
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "request_session", Mock(return_value=session))
    monkeypatch.setattr(consumer, "get_latest_export_cron_num", Mock(return_value=11))
    start_export = Mock()
    monkeypatch.setattr(consumer, "start_product_export", start_export)
    monkeypatch.setattr(
        consumer, "download_latest_export_content", Mock(return_value=downloaded)
    )
    delete_archive = Mock()
    monkeypatch.setattr(consumer, "delete_archive_from_admin", delete_archive)
    publish = Mock()
    monkeypatch.setattr(consumer, "publish_current_snapshot", publish)
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_failure", failure)

    consumer.handle_request(message, bus)

    start_export.assert_called_once_with(session, settings)
    consumer.download_latest_export_content.assert_called_once_with(
        session, settings, after_cron_num=11
    )
    delete_archive.assert_called_once_with(session, settings, "archive.zip")
    publish.assert_called_once_with(bus, message, downloaded)
    failure.assert_not_called()

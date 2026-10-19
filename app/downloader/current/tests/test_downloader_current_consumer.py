"""Tests for the current downloader Kafka contract."""

from unittest.mock import Mock

from app.downloader.current import consumer
from app.downloader.current.models import DownloadedCsv
from app.messaging.models import Envelope


def test_download_handler_authenticates_fetches_cleans_and_replies(monkeypatch):
    settings = object()
    session = object()
    request = Envelope.create("download_csv", {}, reply_to="response")
    downloaded = DownloadedCsv(
        cron_num=12,
        filename="export.csv",
        content=b"csv bytes",
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
    monkeypatch.setattr(consumer, "delete_archive_from_admin", Mock())
    publish = Mock()
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_download", publish)
    monkeypatch.setattr(consumer, "publish_reply", failure)
    bus = object()

    consumer.handle_request(request, bus)

    consumer.get_latest_export_cron_num.assert_called_once_with(session, settings)
    start_export.assert_called_once_with(session, settings)
    consumer.download_latest_export_content.assert_called_once_with(
        session, settings, after_cron_num=11
    )
    consumer.delete_archive_from_admin.assert_called_once_with(
        session, settings, downloaded.archive_filename
    )
    publish.assert_called_once_with(bus, request, downloaded)
    failure.assert_not_called()

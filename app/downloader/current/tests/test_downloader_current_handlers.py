"""Tests for the current downloader's failure path, producer and wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.downloader.current import consumer, producer
from app.downloader.current.models import DownloadedCsv
from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes
from app.messaging.topics import CURRENT_DOWNLOAD_REQUESTS, CURRENT_DOWNLOAD_RESPONSES


def make_request():
    return Envelope.create(
        "download_current",
        {},
        correlation_id="c-1",
        reply_to=CURRENT_DOWNLOAD_RESPONSES,
    )


@pytest.fixture
def steps(monkeypatch):
    """Mock each CMS step so a test can break exactly one of them."""
    parts = type("Steps", (), {})()
    parts.reply = Mock()
    parts.publish = Mock()
    parts.delete = Mock()
    parts.export = Mock()
    parts.download = Mock(return_value="downloaded")
    monkeypatch.setattr(consumer, "load_settings", lambda: "settings")
    monkeypatch.setattr(consumer, "request_session", Mock(return_value="session"))
    monkeypatch.setattr(consumer, "get_latest_export_cron_num", Mock(return_value=4))
    monkeypatch.setattr(consumer, "start_product_export", parts.export)
    monkeypatch.setattr(consumer, "download_latest_export_content", parts.download)
    monkeypatch.setattr(consumer, "delete_archive_from_admin", parts.delete)
    monkeypatch.setattr(consumer, "publish_download", parts.publish)
    monkeypatch.setattr(consumer, "publish_reply", parts.reply)
    return parts


def test_download_failure_is_returned_as_an_error_reply(steps):
    steps.download.side_effect = RuntimeError("export never finished")
    bus = object()
    request = make_request()

    consumer.handle_request(request, bus)

    steps.reply.assert_called_once_with(bus, request, error="export never finished")
    steps.publish.assert_not_called()
    steps.delete.assert_not_called()


def test_a_failure_before_the_export_starts_is_also_reported(steps, monkeypatch):
    def broken_settings():
        raise ValueError("Missing required environment setting(s): TAPTOP_ACCESS")

    monkeypatch.setattr(consumer, "load_settings", broken_settings)

    consumer.handle_request(make_request(), object())

    assert "TAPTOP_ACCESS" in steps.reply.call_args.kwargs["error"]
    steps.export.assert_not_called()


def test_main_runs_the_current_downloader_worker(monkeypatch):
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
    assert args[:3] == (
        "localhost:9092",
        CURRENT_DOWNLOAD_REQUESTS,
        "current-downloader-service",
    )
    assert args[3].func is consumer.handle_request
    assert args[3].keywords == {"settings": settings}
    assert kwargs == {"service_name": "downloader_current"}


def test_publish_download_sends_metadata_and_compressed_content(monkeypatch):
    publish_reply = Mock()
    monkeypatch.setattr(producer, "publish_reply", publish_reply)
    bus = object()
    request = make_request()
    downloaded = DownloadedCsv(
        cron_num=7,
        filename="export.csv",
        content=b"article;price\nA;1\n",
        archive_filename="export.zip",
    )

    producer.publish_download(bus, request, downloaded)

    args = publish_reply.call_args.args
    assert args[:2] == (bus, request)
    assert args[2]["cron_num"] == 7
    assert args[2]["filename"] == "export.csv"
    assert decode_bytes(args[2]["csv_gzip_base64"]) == b"article;price\nA;1\n"


def test_response_topic_is_the_current_download_topic():
    assert producer.response_topic() == CURRENT_DOWNLOAD_RESPONSES

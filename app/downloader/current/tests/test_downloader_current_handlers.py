"""Tests for current downloader events, failures and worker wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from app.contracts.models import Envelope
from app.downloader.current import consumer, producer
from app.downloader.current.models import DownloadedCsv
from app.messaging.payloads import decode_bytes
from app.messaging.exceptions import RetryableMessageError
from app.messaging.topics import CURRENT_DOWNLOADS, REFERENCE_DOWNLOADS


@pytest.fixture(autouse=True)
def bypass_rate_limit_setup(monkeypatch):
    """Keep handler tests independent of Kafka infrastructure."""
    monkeypatch.setattr(consumer, "rate_limit_session", lambda session, *_: session)


def make_request():
    return Envelope.create(
        "reference_downloaded",
        {"reference_sha256": "reference-hash"},
        correlation_id="c-1",
    )


@pytest.fixture
def steps(monkeypatch):
    """Mock each CMS step so a test can break exactly one of them."""
    parts = SimpleNamespace(
        failure=Mock(),
        publish=Mock(),
        delete=Mock(),
        export=Mock(),
        download=Mock(
            return_value=DownloadedCsv(
                cron_num=5,
                filename="current.csv",
                content=b"current csv",
                archive_filename="archive.zip",
            )
        ),
    )
    monkeypatch.setattr(consumer, "load_settings", lambda: "settings")
    monkeypatch.setattr(consumer, "request_session", Mock(return_value="session"))
    monkeypatch.setattr(consumer, "get_latest_export_cron_num", Mock(return_value=4))
    monkeypatch.setattr(consumer, "start_product_export", parts.export)
    monkeypatch.setattr(consumer, "download_latest_export_content", parts.download)
    monkeypatch.setattr(consumer, "delete_archive_from_admin", parts.delete)
    monkeypatch.setattr(consumer, "publish_current_snapshot", parts.publish)
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    return parts


def test_download_failure_is_reported_and_stops_processing(steps):
    steps.download.side_effect = RuntimeError("export never finished")
    bus = object()
    request = make_request()

    consumer.handle_request(request, bus)

    steps.failure.assert_called_once()
    assert str(steps.failure.call_args.args[2]) == "export never finished"
    steps.publish.assert_not_called()
    steps.delete.assert_not_called()


def test_transient_cms_network_failure_is_reported_and_left_for_retry(steps):
    steps.download.side_effect = requests.ConnectionError("CMS unavailable")

    with pytest.raises(RetryableMessageError, match="Transient failure"):
        consumer.handle_request(make_request(), object())

    steps.failure.assert_called_once()
    steps.publish.assert_not_called()


def test_a_failure_before_the_export_starts_is_also_reported(steps, monkeypatch):
    def broken_settings():
        raise ValueError("Missing required environment setting(s): TAPTOP_ACCESS")

    monkeypatch.setattr(consumer, "load_settings", broken_settings)

    consumer.handle_request(make_request(), object())

    assert "TAPTOP_ACCESS" in str(steps.failure.call_args.args[2])
    steps.export.assert_not_called()


def test_unexpected_event_command_is_reported_without_contacting_cms(steps):
    message = Envelope.create("unrecognized", {}, correlation_id="pipeline-bad-command")

    consumer.handle_request(message, object())

    assert "Unsupported current downloader command" in str(
        steps.failure.call_args.args[2]
    )
    assert steps.failure.call_args.args[3] == "pipeline-bad-command"
    steps.export.assert_not_called()


def test_main_subscribes_to_reference_changes(monkeypatch):
    run_consumer = Mock()
    settings = SimpleNamespace(bootstrap_servers="localhost:9092")
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == (
        "localhost:9092",
        REFERENCE_DOWNLOADS,
        "current-downloader-service",
    )
    assert args[3].func is consumer.handle_request
    assert args[3].keywords == {"settings": settings}
    assert kwargs == {"service_name": "downloader_current"}


def test_publish_event_contains_only_current_csv_and_preserves_correlation():
    bus = Mock()
    reference_event = make_request()
    downloaded = DownloadedCsv(
        cron_num=7,
        filename="export.csv",
        content=b"article;price\nA;1\n",
        archive_filename="export.zip",
    )

    event = producer.publish_current_snapshot(bus, reference_event, downloaded)

    bus.publish.assert_called_once_with(CURRENT_DOWNLOADS, event, key="c-1")
    assert event.correlation_id == "c-1"
    assert (
        decode_bytes(event.payload["current_csv_gzip_base64"])
        == b"article;price\nA;1\n"
    )
    assert "reference_csv_gzip_base64" not in event.payload
    assert "reference_sha256" not in event.payload
    assert event.payload["current_cron_num"] == 7
    assert event.payload["current_filename"] == "export.csv"

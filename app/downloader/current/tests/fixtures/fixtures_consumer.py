"""Fixtures for the current downloader consumer tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def current_bypass_rate_limit(monkeypatch):
    """Keep handler tests independent of Kafka infrastructure."""
    from app.downloader.current import consumer

    monkeypatch.setattr(consumer, "rate_limit_session", lambda session, *_: session)


@pytest.fixture
def current_steps(monkeypatch):
    """Mock each CMS step so a test can break exactly one of them."""
    from app.downloader.current.models import DownloadedCsv
    from app.downloader.current import consumer

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

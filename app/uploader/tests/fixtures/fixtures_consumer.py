"""Fixtures for the uploader consumer tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def uploader_bypass_rate_limit(monkeypatch):
    """Keep consumer contract tests independent of Kafka infrastructure."""
    from app.uploader import consumer

    monkeypatch.setattr(consumer, "rate_limit_session", lambda session, *_: session)


@pytest.fixture
def uploader_steps(monkeypatch):
    """Mock every CMS step and the service failure publisher."""
    from app.uploader import consumer

    parts = SimpleNamespace(
        failure=Mock(),
        delete=Mock(),
        upload=Mock(),
        wait=Mock(),
        start_import=Mock(),
    )
    monkeypatch.setattr(consumer, "load_settings", lambda: "settings")
    monkeypatch.setattr(consumer, "request_session", Mock(return_value="session"))
    monkeypatch.setattr(consumer, "upload_processed_content", parts.upload)
    monkeypatch.setattr(consumer, "get_latest_import_cron_num", Mock(return_value=1))
    monkeypatch.setattr(consumer, "start_product_import", parts.start_import)
    monkeypatch.setattr(consumer, "wait_for_import_completion", parts.wait)
    monkeypatch.setattr(consumer, "delete_uploaded_file", parts.delete)
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    return parts

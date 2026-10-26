"""Fixtures for the current downloader queue tests."""

import pytest


@pytest.fixture
def current_no_sleep(monkeypatch):
    from app.downloader.current import queue_processor

    delays = []
    monkeypatch.setattr(queue_processor, "sleep", delays.append)
    return delays

"""Fixtures for the current downloader queue tests."""

import pytest

from app.downloader.current import queue_processor


@pytest.fixture
def current_no_sleep(monkeypatch):
    delays = []
    monkeypatch.setattr(queue_processor, "sleep", delays.append)
    return delays

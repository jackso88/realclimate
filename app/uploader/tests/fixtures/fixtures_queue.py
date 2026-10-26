"""Fixtures for the uploader queue processor tests."""

import pytest


@pytest.fixture
def uploader_no_sleep(monkeypatch):
    """Skip real waiting between polls and record the requested delays."""
    from app.uploader import queue_processor

    delays = []
    monkeypatch.setattr(queue_processor, "sleep", delays.append)
    return delays

"""Fixtures for the admin authentication consumer tests."""

import pytest

from app.admin_auth import consumer


@pytest.fixture
def admin_empty_session_cache():
    """Keep the module-level session cache from leaking between tests."""
    consumer.session_cache.clear()
    yield
    consumer.session_cache.clear()

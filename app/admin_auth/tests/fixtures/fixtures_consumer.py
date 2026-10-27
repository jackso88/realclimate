"""Fixtures for the admin authentication consumer tests."""

import pytest


@pytest.fixture
def admin_empty_session_cache():
    """Keep the module-level session cache from leaking between tests."""
    from app.admin_auth import consumer

    consumer.session_cache.clear()
    yield
    consumer.session_cache.clear()

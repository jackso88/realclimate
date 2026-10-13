"""Tests for the authentication request consumer's cache integration."""

from unittest.mock import Mock

from app.admin_auth import consumer
from app.admin_auth.models import AdminSettings, SessionSnapshot


def test_requests_reuse_cached_snapshot(monkeypatch):
    settings = AdminSettings(
        base_url="https://admin.invalid",
        cms_url="https://admin.invalid/cms",
        username="user",
        password="secret",
        access="token",
        ver_id=123,
        design_id=456,
    )
    snapshot = SessionSnapshot([], {"X-Session": "cached"})
    authenticate = Mock(return_value=snapshot)
    publish = Mock()
    bus = object()
    request = Mock()
    consumer.session_cache.clear()
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "create_session_snapshot", authenticate)
    monkeypatch.setattr(consumer, "publish_reply", publish)

    try:
        consumer.handle_request(request, bus)
        consumer.handle_request(request, bus)
    finally:
        consumer.session_cache.clear()

    authenticate.assert_called_once_with(settings)
    assert publish.call_count == 2
    assert all(call.args[2] == snapshot.to_payload() for call in publish.call_args_list)

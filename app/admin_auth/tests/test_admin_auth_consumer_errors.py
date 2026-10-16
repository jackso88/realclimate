"""Tests for admin_auth failure handling and worker wiring."""

from unittest.mock import Mock

import pytest

from app.admin_auth import consumer
from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings, SessionSnapshot
from app.messaging.topics import ADMIN_AUTH_REQUESTS

SETTINGS = AdminSettings(
    base_url="https://admin.invalid",
    cms_url="https://admin.invalid/cms",
    username="user",
    password="secret",
    access="token",
    ver_id=123,
    design_id=456,
)


@pytest.fixture(autouse=True)
def empty_cache():
    """Keep the module-level session cache from leaking between tests."""
    consumer.session_cache.clear()
    yield
    consumer.session_cache.clear()


def test_invalid_settings_are_reported_as_an_error_reply(monkeypatch):
    def broken_settings():
        raise AdminLoginError("Missing required settings: TAPTOP_USERNAME")

    publish = Mock()
    monkeypatch.setattr(consumer, "load_settings", broken_settings)
    monkeypatch.setattr(consumer, "publish_reply", publish)
    bus = object()
    request = Mock()

    consumer.handle_request(request, bus)

    publish.assert_called_once_with(
        bus, request, error="Missing required settings: TAPTOP_USERNAME"
    )


def test_failed_login_is_reported_and_not_cached(monkeypatch):
    snapshot = SessionSnapshot([], {"X-Session": "fresh"})
    authenticate = Mock(side_effect=[AdminLoginError("login rejected"), snapshot])
    publish = Mock()
    monkeypatch.setattr(consumer, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(consumer, "create_session_snapshot", authenticate)
    monkeypatch.setattr(consumer, "publish_reply", publish)
    bus = object()
    request = Mock()

    consumer.handle_request(request, bus)
    consumer.handle_request(request, bus)

    assert authenticate.call_count == 2
    first, second = publish.call_args_list
    assert first.kwargs == {"error": "login rejected"}
    assert second.args[2] == snapshot.to_payload()


def test_main_runs_the_admin_auth_worker(monkeypatch):
    run_consumer = Mock()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    consumer.main()

    run_consumer.assert_called_once_with(
        "localhost:9092",
        ADMIN_AUTH_REQUESTS,
        "admin-auth-service",
        consumer.handle_request,
        service_name="admin_auth",
    )

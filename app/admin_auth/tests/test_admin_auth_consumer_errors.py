"""Tests for admin_auth failure handling and worker wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.admin_auth import consumer
from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings, SessionSnapshot
from app.messaging.topics import ADMIN_AUTH_REQUESTS

pytestmark = pytest.mark.usefixtures("admin_empty_session_cache")

SETTINGS = AdminSettings(
    base_url="https://admin.invalid",
    cms_url="https://admin.invalid/cms",
    username="user",
    password="secret",
    access="token",
    ver_id=123,
    design_id=456,
)


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
    snapshot = SessionSnapshot(cookies=[], headers={"X-Session": "fresh"})
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
    settings = SimpleNamespace(bootstrap_servers="localhost:9092")
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(
        consumer,
        "load_settings",
        lambda: settings,
    )

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == ("localhost:9092", ADMIN_AUTH_REQUESTS, "admin-auth-service")
    assert args[3].func is consumer.handle_request
    assert args[3].keywords == {"settings": settings}
    assert kwargs == {"service_name": "admin_auth"}

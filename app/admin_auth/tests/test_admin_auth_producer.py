"""Tests for the client helper that requests a CMS session over Kafka."""

from unittest.mock import Mock

from app.admin_auth.producer import request_session
from app.messaging.models import Envelope
from app.messaging.topics import ADMIN_AUTH_REQUESTS


def make_reply():
    return Envelope.create(
        "response",
        {
            "cookies": [
                {
                    "name": "sid",
                    "value": "abc123",
                    "domain": "admin.invalid",
                    "path": "/",
                    "secure": True,
                    "expires": None,
                    "rest": {},
                }
            ],
            "headers": {"X-Session": "cached"},
        },
    )


def test_request_session_asks_the_auth_service_for_a_session():
    bus = Mock()
    bus.request.return_value = make_reply()

    request_session(bus, "my.responses", "my-group")

    bus.request.assert_called_once_with(
        ADMIN_AUTH_REQUESTS,
        "my.responses",
        "create_session",
        {},
        timeout=60,
        response_group="my-group",
    )


def test_request_session_restores_cookies_and_headers():
    bus = Mock()
    bus.request.return_value = make_reply()

    session = request_session(bus, "my.responses", "my-group")

    assert session.headers["X-Session"] == "cached"
    assert [cookie.name for cookie in session.cookies] == ["sid"]
    assert session.cookies.get("sid", domain="admin.invalid") == "abc123"


def test_request_session_passes_a_custom_timeout():
    bus = Mock()
    bus.request.return_value = make_reply()

    request_session(bus, "my.responses", "my-group", timeout=5)

    assert bus.request.call_args.kwargs["timeout"] == 5

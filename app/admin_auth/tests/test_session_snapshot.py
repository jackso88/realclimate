"""Tests for JSON-safe authenticated session transfer."""

import requests

from app.admin_auth.models import SessionSnapshot


def test_session_snapshot_restores_cookie_and_headers():
    session = requests.Session()
    session.headers["X-Test"] = "value"
    session.cookies.set("session", "cookie-value", domain="example.test", path="/")

    snapshot = SessionSnapshot.from_payload(
        SessionSnapshot.from_session(session).to_payload()
    )
    restored = snapshot.create_session()

    assert restored.headers["X-Test"] == "value"
    assert restored.cookies.get("session", domain="example.test") == "cookie-value"

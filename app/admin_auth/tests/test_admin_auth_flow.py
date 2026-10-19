"""Tests for the CMS login and redirect flow."""

from unittest.mock import Mock

import pytest
import requests

from app.admin_auth.auth import create_session_snapshot, extract_javascript_redirect
from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings


def make_settings():
    return AdminSettings(
        base_url="https://admin.invalid",
        cms_url="https://admin.invalid/-/cms/v1",
        username="test-user",
        password="test-password",
        access="test-access",
        ver_id=123,
        design_id=456,
    )


def test_extract_javascript_redirect_resolves_relative_url():
    redirect = extract_javascript_redirect(
        "<script>window.document.location = '/login?mcc=test';</script>",
        "https://admin.invalid/login",
    )

    assert redirect == "https://admin.invalid/login?mcc=test"


def test_extract_javascript_redirect_requires_supported_assignment():
    with pytest.raises(AdminLoginError, match="Could not find"):
        extract_javascript_redirect(
            "<script>window.location='/elsewhere';</script>",
            "https://admin.invalid/login",
        )


def test_posts_credentials_then_follows_redirect(monkeypatch):
    session = requests.Session()
    session.cookies.set("session", "cookie-value", domain="admin.invalid", path="/")
    login_response = Mock(
        text="<script>window.document.location = '/login?mcc=test';</script>",
        url="https://admin.invalid/login",
    )
    redirect_response = Mock(url="https://admin.invalid/login?mcc=test")
    mosaic_response = Mock(url="https://admin.invalid/-/cms/v1/mosaic/")
    session.post = Mock(return_value=login_response)
    session.get = Mock(side_effect=[redirect_response, mosaic_response])
    monkeypatch.setattr("app.admin_auth.auth.requests.Session", lambda: session)
    rate_limit = Mock(side_effect=lambda value, *_: value)
    monkeypatch.setattr("app.admin_auth.auth.rate_limit_session", rate_limit)

    snapshot = create_session_snapshot(make_settings())

    rate_limit.assert_called_once_with(
        session, "localhost:9092", "admin_auth", "cms:account"
    )

    session.post.assert_called_once_with(
        "https://admin.invalid/login",
        data={
            "email": "test-user",
            "password": "test-password",
            "_form": "login_form",
        },
        timeout=30,
    )
    assert session.get.call_args_list[0].args == (
        "https://admin.invalid/login?mcc=test",
    )
    assert session.get.call_args_list[1].args == (
        "https://admin.invalid/-/cms/v1/mosaic/",
    )
    assert session.get.call_args_list[1].kwargs["params"] == [
        ("act", "main"),
        ("access", "test-access"),
        ("ver_id", "123"),
        ("design_id", "456"),
    ]
    assert snapshot.create_session().cookies.get("session") == "cookie-value"
    login_response.raise_for_status.assert_called_once()
    redirect_response.raise_for_status.assert_called_once()
    mosaic_response.raise_for_status.assert_called_once()


def test_create_session_raises_for_failed_login_response(monkeypatch):
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("unauthorized")
    session = Mock(post=Mock(return_value=response))
    monkeypatch.setattr("app.admin_auth.auth.requests.Session", lambda: session)

    with pytest.raises(requests.HTTPError, match="unauthorized"):
        create_session_snapshot(make_settings())

    session.get.assert_not_called()

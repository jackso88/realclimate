"""Tests for OAuth fallbacks when a cached Google token cannot be reused."""

from unittest.mock import Mock

import pytest

from app.downloader.reference import google_oauth
from app.downloader.reference.exceptions import ReferenceAuthenticationError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def install_flow(monkeypatch, flow):
    monkeypatch.setattr(
        google_oauth.InstalledAppFlow,
        "from_client_secrets_file",
        Mock(return_value=flow),
    )


def install_cached_token(monkeypatch, cached):
    monkeypatch.setattr(
        google_oauth.UserCredentials,
        "from_authorized_user_file",
        Mock(return_value=cached),
    )
    monkeypatch.setattr(google_oauth, "Request", Mock())


def test_failed_refresh_falls_back_to_the_interactive_flow(
    monkeypatch, reference_oauth_files
):
    credentials_file, token_file = reference_oauth_files
    expired = Mock(valid=False, expired=True, refresh_token="refresh")
    expired.refresh.side_effect = RuntimeError("token revoked")
    fresh = Mock()
    fresh.to_json.return_value = '{"token": "fresh"}'
    flow = Mock()
    flow.run_local_server.return_value = fresh
    install_cached_token(monkeypatch, expired)
    install_flow(monkeypatch, flow)

    result = google_oauth.get_credentials(credentials_file, token_file, SCOPES)

    assert result is fresh
    assert token_file.read_text(encoding="utf-8") == '{"token": "fresh"}'
    flow.run_local_server.assert_called_once_with(
        port=0,
        open_browser=False,
        access_type="offline",
        prompt="consent",
    )


def test_expired_token_without_a_refresh_token_needs_a_new_authorization(
    monkeypatch, reference_oauth_files
):
    credentials_file, token_file = reference_oauth_files
    expired = Mock(valid=False, expired=True, refresh_token=None)
    fresh = Mock()
    fresh.to_json.return_value = "{}"
    flow = Mock()
    flow.run_local_server.return_value = fresh
    install_cached_token(monkeypatch, expired)
    install_flow(monkeypatch, flow)

    result = google_oauth.get_credentials(credentials_file, token_file, SCOPES)

    assert result is fresh
    expired.refresh.assert_not_called()


def test_a_failed_authorization_is_wrapped_and_keeps_its_cause(
    monkeypatch, reference_oauth_files
):
    credentials_file, token_file = reference_oauth_files
    token_file.unlink()
    flow = Mock()
    flow.run_local_server.side_effect = OSError("address already in use")
    install_flow(monkeypatch, flow)

    with pytest.raises(ReferenceAuthenticationError) as error:
        google_oauth.get_credentials(credentials_file, token_file, SCOPES)

    assert isinstance(error.value.__cause__, OSError)
    assert not token_file.exists()

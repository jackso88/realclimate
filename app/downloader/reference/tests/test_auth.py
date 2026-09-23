"""Unit tests for OAuth credential helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.downloader.reference.auth import get_credentials

SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


class TestGetCredentials:
    """Tests for :func:`get_credentials`."""

    def test_missing_credentials_file_raises(self, tmp_path: Path) -> None:
        creds = tmp_path / "missing.json"
        token = tmp_path / "token.json"
        with pytest.raises(FileNotFoundError, match="OAuth credentials file"):
            get_credentials(creds, token, SCOPES)

    def test_returns_valid_cached_token(self, tmp_path: Path) -> None:
        creds_file = tmp_path / "client_secrets.json"
        creds_file.write_text("{}", encoding="utf-8")
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")

        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch(
            "app.downloader.reference.auth.UserCredentials.from_authorized_user_file",
            return_value=mock_creds,
        ) as from_file:
            result = get_credentials(creds_file, token_file, SCOPES)

        from_file.assert_called_once_with(str(token_file), SCOPES)
        assert result is mock_creds

    def test_refreshes_expired_token(self, tmp_path: Path) -> None:
        creds_file = tmp_path / "client_secrets.json"
        creds_file.write_text("{}", encoding="utf-8")
        token_file = tmp_path / "token.json"
        token_file.write_text("{}", encoding="utf-8")

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.to_json.return_value = '{"token": "new"}'

        with (
            patch(
                "app.downloader.reference.auth.UserCredentials.from_authorized_user_file",
                return_value=mock_creds,
            ),
            patch("app.downloader.reference.auth.Request"),
        ):
            result = get_credentials(creds_file, token_file, SCOPES)

        mock_creds.refresh.assert_called_once()
        assert result is mock_creds
        assert token_file.read_text(encoding="utf-8") == '{"token": "new"}'

    def test_starts_flow_when_no_token(self, tmp_path: Path) -> None:
        creds_file = tmp_path / "client_secrets.json"
        creds_file.write_text("{}", encoding="utf-8")
        token_file = tmp_path / "token.json"

        mock_flow = MagicMock()
        mock_new_creds = MagicMock()
        mock_new_creds.to_json.return_value = '{"token": "fresh"}'
        mock_flow.run_local_server.return_value = mock_new_creds

        with (
            patch(
                "app.downloader.reference.auth.UserCredentials.from_authorized_user_file",
            ) as from_file,
            patch(
                "app.downloader.reference.auth.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ),
        ):
            # No token file exists, so from_authorized_user_file is never called.
            from_file.side_effect = FileNotFoundError
            result = get_credentials(creds_file, token_file, SCOPES)

        mock_flow.run_local_server.assert_called_once_with(
            port=0,
            open_browser=False,
            access_type="offline",
            prompt="consent",
        )
        assert result is mock_new_creds
        assert token_file.read_text(encoding="utf-8") == '{"token": "fresh"}'

    def test_corrupted_token_triggers_flow(self, tmp_path: Path) -> None:
        creds_file = tmp_path / "client_secrets.json"
        creds_file.write_text("{}", encoding="utf-8")
        token_file = tmp_path / "token.json"
        token_file.write_text("not-json", encoding="utf-8")

        mock_flow = MagicMock()
        mock_new_creds = MagicMock()
        mock_new_creds.to_json.return_value = '{"token": "reauth"}'
        mock_flow.run_local_server.return_value = mock_new_creds

        with (
            patch(
                "app.downloader.reference.auth.UserCredentials.from_authorized_user_file",
                side_effect=ValueError("bad token"),
            ),
            patch(
                "app.downloader.reference.auth.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ),
        ):
            result = get_credentials(creds_file, token_file, SCOPES)

        assert result is mock_new_creds
        assert token_file.read_text(encoding="utf-8") == '{"token": "reauth"}'

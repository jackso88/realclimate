"""Unit tests for configuration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.downloader.reference.config import extract_spreadsheet_id, load_settings
from app.downloader.reference.models import Settings


class TestExtractSpreadsheetId:
    """Tests for :func:`extract_spreadsheet_id`."""

    def test_bare_id(self) -> None:
        spreadsheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        assert extract_spreadsheet_id(spreadsheet_id) == spreadsheet_id

    def test_full_url(self) -> None:
        url = (
            "https://docs.google.com/spreadsheets/d/"
            "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
        )
        assert (
            extract_spreadsheet_id(url)
            == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        )

    def test_url_with_trailing_slash(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/" "abc123XYZ_-/edit"
        assert extract_spreadsheet_id(url) == "abc123XYZ_-"

    def test_strips_whitespace(self) -> None:
        spreadsheet_id = "  simple-id  "
        assert extract_spreadsheet_id(spreadsheet_id) == "simple-id"

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot extract spreadsheet ID"):
            extract_spreadsheet_id("https://example.com/not-a-sheet")


class TestLoadSettings:
    """Tests for :func:`load_settings`."""

    def test_missing_env_file_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.env"
        with pytest.raises(FileNotFoundError, match=".env not found"):
            load_settings(dotenv_path=missing)

    def test_loads_required_variables(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/abc123/edit",
                    "GOOGLE_SHEET_NAME=Sheet1",
                    "GOOGLE_CREDENTIALS_FILE=creds.json",
                    "GOOGLE_TOKEN_FILE=token.json",
                ]
            ),
            encoding="utf-8",
        )

        # Ensure no leakage from the real environment.
        for key in (
            "GOOGLE_SHEET_URL",
            "GOOGLE_SHEET_NAME",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
            "GOOGLE_AUTH_MODE",
            "GOOGLE_SERVICE_ACCOUNT_FILE",
        ):
            monkeypatch.delenv(key, raising=False)

        settings = load_settings(dotenv_path=env_file)

        assert isinstance(settings, Settings)
        assert settings.spreadsheet_url.endswith("abc123/edit")
        assert settings.sheet_name == "Sheet1"
        assert settings.credentials_file == tmp_path / "creds.json"
        assert settings.token_file == tmp_path / "token.json"

    def test_loads_from_environment_without_dotenv_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GOOGLE_SHEET_URL", "https://sheets.example.test/id")
        monkeypatch.setenv("GOOGLE_SHEET_NAME", "Catalog")
        monkeypatch.setenv("GOOGLE_AUTH_MODE", "user")
        monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "/run/secrets/client.json")
        monkeypatch.setenv("GOOGLE_TOKEN_FILE", "/var/lib/app/token.json")

        settings = load_settings()

        assert settings.spreadsheet_url == "https://sheets.example.test/id"
        assert settings.sheet_name == "Catalog"
        assert settings.credentials_file == Path("/run/secrets/client.json")
        assert settings.token_file == Path("/var/lib/app/token.json")

    def test_loads_service_account_mode_without_user_oauth_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("", encoding="utf-8")
        monkeypatch.setenv("GOOGLE_SHEET_URL", "https://sheets.example.test/id")
        monkeypatch.setenv("GOOGLE_SHEET_NAME", "Catalog")
        monkeypatch.setenv("GOOGLE_AUTH_MODE", "service_account")
        monkeypatch.setenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE",
            "/app/app/downloader/reference/credentials/service_account_secret.json",
        )
        monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)
        monkeypatch.delenv("GOOGLE_TOKEN_FILE", raising=False)

        settings = load_settings(dotenv_path=env_file)

        assert settings.auth_mode == "service_account"
        assert settings.credentials_file is None
        assert settings.token_file is None
        assert settings.service_account_file == Path(
            "/app/app/downloader/reference/credentials/service_account_secret.json"
        )

    def test_rejects_unknown_auth_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_SHEET_URL", "https://sheets.example.test/id")
        monkeypatch.setenv("GOOGLE_SHEET_NAME", "Catalog")
        monkeypatch.setenv("GOOGLE_AUTH_MODE", "unsupported")

        with pytest.raises(RuntimeError, match="GOOGLE_AUTH_MODE"):
            load_settings()

    def test_missing_variable_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "GOOGLE_SHEET_URL=https://example.com\n",
            encoding="utf-8",
        )
        for key in (
            "GOOGLE_SHEET_URL",
            "GOOGLE_SHEET_NAME",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
            "GOOGLE_AUTH_MODE",
            "GOOGLE_SERVICE_ACCOUNT_FILE",
        ):
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(RuntimeError, match="Missing environment variable"):
            load_settings(dotenv_path=env_file)

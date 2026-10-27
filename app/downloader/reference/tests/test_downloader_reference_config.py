"""Unit tests for configuration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.downloader.reference.config import (
    PROJECT_ROOT,
    extract_spreadsheet_id,
    load_settings,
)
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

    def test_loads_required_variables_and_resolves_relative_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "GOOGLE_SHEET_URL", "https://docs.google.com/spreadsheets/d/abc123/edit"
        )
        monkeypatch.setenv("GOOGLE_SHEET_NAME", "Sheet1")
        monkeypatch.setenv("GOOGLE_CREDENTIALS_FILE", "creds.json")
        monkeypatch.setenv("GOOGLE_TOKEN_FILE", "token.json")
        monkeypatch.delenv("GOOGLE_AUTH_MODE", raising=False)
        monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)

        settings = load_settings()

        assert isinstance(settings, Settings)
        assert settings.spreadsheet_url.endswith("abc123/edit")
        assert settings.sheet_name == "Sheet1"
        assert settings.credentials_file == PROJECT_ROOT / "creds.json"
        assert settings.token_file == PROJECT_ROOT / "token.json"

    def test_project_root_is_the_repository_root(self) -> None:
        assert (PROJECT_ROOT / "app" / "downloader" / "reference").is_dir()

    def test_loads_absolute_paths_unchanged(
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
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GOOGLE_SHEET_URL", "https://sheets.example.test/id")
        monkeypatch.setenv("GOOGLE_SHEET_NAME", "Catalog")
        monkeypatch.setenv("GOOGLE_AUTH_MODE", "service_account")
        monkeypatch.setenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE",
            "/app/app/downloader/reference/credentials/service_account_secret.json",
        )
        monkeypatch.delenv("GOOGLE_CREDENTIALS_FILE", raising=False)
        monkeypatch.delenv("GOOGLE_TOKEN_FILE", raising=False)

        settings = load_settings()

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

    def test_missing_variable_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in (
            "GOOGLE_SHEET_NAME",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
            "GOOGLE_AUTH_MODE",
            "GOOGLE_SERVICE_ACCOUNT_FILE",
        ):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("GOOGLE_SHEET_URL", "https://example.com")

        with pytest.raises(RuntimeError, match="Missing environment variable"):
            load_settings()

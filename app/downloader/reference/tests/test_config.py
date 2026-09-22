from pathlib import Path

import pytest

from app.downloader.reference.config import extract_spreadsheet_id, load_settings


def test_extract_spreadsheet_id_from_url() -> None:
    url = "https://docs.google.com/spreadsheets/d/abc_123-XYZ/edit#gid=0"
    assert extract_spreadsheet_id(url) == "abc_123-XYZ"


def test_extract_spreadsheet_id_from_raw_id() -> None:
    assert extract_spreadsheet_id("abc_123-XYZ") == "abc_123-XYZ"


def test_extract_spreadsheet_id_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        extract_spreadsheet_id("https://example.com/foo")


def test_load_settings_resolves_paths_relative_to_dotenv(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "GOOGLE_SHEET_URL=https://docs.google.com/spreadsheets/d/abc/edit\n"
        "GOOGLE_SHEET_NAME=Лист1\n"
        "GOOGLE_CREDENTIALS_FILE=credentials.json\n"
        "GOOGLE_TOKEN_FILE=token.json\n"
        "GOOGLE_OUTPUT_FILE=table.xlsx\n",
        encoding="utf-8",
    )

    settings = load_settings(env)

    assert settings.credentials_file == tmp_path / "credentials.json"
    assert settings.token_file == tmp_path / "token.json"
    assert settings.output_file == tmp_path / "table.xlsx"

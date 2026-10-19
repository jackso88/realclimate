"""Data transfer objects for the Google Sheets downloader."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable spreadsheet and authentication configuration."""

    spreadsheet_url: str
    sheet_name: str
    credentials_file: Path | None
    token_file: Path | None
    auth_mode: str = "user"
    service_account_file: Path | None = None

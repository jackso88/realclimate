"""Data transfer objects for the Google Sheets downloader."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable configuration required to download a spreadsheet."""

    spreadsheet_url: str
    sheet_name: str
    credentials_file: Path
    token_file: Path
    output_file: Path
    chunk_rows: int = 2000

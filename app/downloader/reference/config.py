from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


@dataclass(frozen=True)
class Settings:
    spreadsheet_url: str
    sheet_name: str
    credentials_file: Path
    token_file: Path
    output_file: Path
    chunk_rows: int = 2000


def extract_spreadsheet_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        return value
    match = SPREADSHEET_ID_RE.search(value)
    if not match:
        raise ValueError(f"Cannot extract spreadsheet ID from: {value!r}")
    return match.group(1)


def _path(value: str, base_dir: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def load_settings(dotenv_path: Path | None = None) -> Settings:
    dotenv_path = dotenv_path or (Path(__file__).resolve().parent.parent / "../../.env")
    base_dir = dotenv_path.resolve().parent
    if not dotenv_path.is_file():
        raise FileNotFoundError(f".env not found: {dotenv_path}")
    load_dotenv(dotenv_path, override=False)

    def required(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"Missing environment variable: {name}")
        return value

    return Settings(
        spreadsheet_url=required("GOOGLE_SHEET_URL"),
        sheet_name=required("GOOGLE_SHEET_NAME"),
        credentials_file=_path(required("GOOGLE_CREDENTIALS_FILE"), base_dir),
        token_file=_path(required("GOOGLE_TOKEN_FILE"), base_dir),
        output_file=_path(required("GOOGLE_OUTPUT_FILE"), base_dir),
    )

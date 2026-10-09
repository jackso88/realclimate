"""Configuration loading and spreadsheet helpers.

Settings are read from a ``.env`` file. Paths that are relative are
resolved against the directory that contains the ``.env`` file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv
from app.downloader.reference.exceptions import ReferenceConfigurationError
from app.downloader.reference.models import Settings

# Regex that extracts the spreadsheet ID from a full Google Sheets URL.
SPREADSHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")

# OAuth2 scopes required to read Google Sheets.
SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


def extract_spreadsheet_id(value: str) -> str:
    """Extract a Google Spreadsheet ID from a URL or raw ID string.

    Accepts either:

    * a full URL containing ``/spreadsheets/d/<ID>``
    * a bare spreadsheet ID (alphanumeric, hyphens, underscores)

    Args:
        value: URL or spreadsheet ID.

    Returns:
        The extracted spreadsheet ID.

    Raises:
        ValueError: If the ID cannot be determined from ``value``.
    """
    value = value.strip()
    if re.fullmatch(r"[a-zA-Z0-9_-]+", value):
        return value

    match = SPREADSHEET_ID_RE.search(value)
    if match is None:
        raise ValueError(f"Cannot extract spreadsheet ID from: {value!r}")
    return match.group(1)


def _resolve_path(value: str, base_dir: Path) -> Path:
    """Resolve a path relative to ``base_dir`` if it is not absolute.

    Args:
        value: Path string from the environment.
        base_dir: Directory used as the root for relative paths.

    Returns:
        An absolute :class:`~pathlib.Path`.
    """
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def load_settings(dotenv_path: Path | None = None) -> Settings:
    """Load application settings from a ``.env`` file.

    Required environment variables:

    * ``GOOGLE_SHEET_URL``
    * ``GOOGLE_SHEET_NAME``
    * ``GOOGLE_CREDENTIALS_FILE``
    * ``GOOGLE_TOKEN_FILE``
    * ``GOOGLE_OUTPUT_FILE``

    Args:
        dotenv_path: Explicit path to the ``.env`` file. When omitted,
            the function looks for ``.env`` two levels above the package
            directory (project root).

    Returns:
        A frozen :class:`Settings` instance.

    Raises:
        FileNotFoundError: If the ``.env`` file does not exist.
        RuntimeError: If a required environment variable is missing.
    """
    if dotenv_path is None:
        # Project root is four levels above this package module.
        dotenv_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"

    base_dir = dotenv_path.resolve().parent
    if not dotenv_path.is_file():
        raise FileNotFoundError(f".env not found: {dotenv_path}")

    load_dotenv(dotenv_path, override=False)

    def required(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise ReferenceConfigurationError(f"Missing environment variable: {name}")
        return value

    return Settings(
        spreadsheet_url=required("GOOGLE_SHEET_URL"),
        sheet_name=required("GOOGLE_SHEET_NAME"),
        credentials_file=_resolve_path(required("GOOGLE_CREDENTIALS_FILE"), base_dir),
        token_file=_resolve_path(required("GOOGLE_TOKEN_FILE"), base_dir),
        output_file=_resolve_path(required("GOOGLE_OUTPUT_FILE"), base_dir),
    )

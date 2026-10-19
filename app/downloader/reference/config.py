"""Configuration loading and spreadsheet helpers.

Settings are read from a ``.env`` file. Paths that are relative are
resolved against the directory that contains the ``.env`` file.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from pydantic import ValidationError

from app.downloader.reference.exceptions import ReferenceConfigurationError
from app.downloader.reference.models import ReferenceDownloaderEnvironment, Settings

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
    """Load application settings from environment variables or a ``.env`` file.

    Required environment variables:

    * ``GOOGLE_SHEET_URL``
    * ``GOOGLE_SHEET_NAME``
    * Optional ``GOOGLE_AUTH_MODE`` (``user`` or ``service_account``; defaults to ``user``)
    * ``GOOGLE_CREDENTIALS_FILE`` and ``GOOGLE_TOKEN_FILE`` in user mode
    * ``GOOGLE_SERVICE_ACCOUNT_FILE`` in service-account mode
    * Optional user OAuth paths in service-account mode for permission-denied
        fallback

    Args:
        dotenv_path: Explicit path to the ``.env`` file. When omitted,
            the function looks for ``.env`` at the project root, four parent
            directories above this module.

    Returns:
        A frozen :class:`Settings` instance.

    Raises:
        FileNotFoundError: If an explicitly supplied ``.env`` file is missing.
        ReferenceConfigurationError: If a required environment variable is missing.
    """
    if dotenv_path is None:
        # Project root is four levels above this package module.
        dotenv_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"

    base_dir = dotenv_path.resolve().parent
    is_repository_default = (
        dotenv_path == Path(__file__).resolve().parent.parent.parent.parent / ".env"
    )
    if not is_repository_default and not dotenv_path.is_file():
        raise FileNotFoundError(f".env not found: {dotenv_path}")

    if dotenv_path.is_file():
        load_dotenv(dotenv_path, override=False)

    values = dict(os.environ)
    auth_mode_value = values.get("GOOGLE_AUTH_MODE", "user").strip().lower()
    required = ["GOOGLE_SHEET_URL", "GOOGLE_SHEET_NAME"]
    if auth_mode_value == "user":
        required.extend(("GOOGLE_CREDENTIALS_FILE", "GOOGLE_TOKEN_FILE"))
    elif auth_mode_value == "service_account":
        required.append("GOOGLE_SERVICE_ACCOUNT_FILE")
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise ReferenceConfigurationError(
            f"Missing environment variable(s): {', '.join(missing)}"
        )

    try:
        config = ReferenceDownloaderEnvironment.model_validate(values)
    except ValidationError as error:
        raise ReferenceConfigurationError(
            f"Invalid reference downloader settings: {error}"
        ) from error

    return Settings(
        spreadsheet_url=config.spreadsheet_url,
        sheet_name=config.sheet_name,
        credentials_file=(
            _resolve_path(str(config.credentials_file), base_dir)
            if config.credentials_file
            else None
        ),
        token_file=(
            _resolve_path(str(config.token_file), base_dir)
            if config.token_file
            else None
        ),
        auth_mode=config.auth_mode,
        service_account_file=(
            _resolve_path(str(config.service_account_file), base_dir)
            if config.service_account_file
            else None
        ),
        bootstrap_servers=config.bootstrap_servers,
    )


def configure_logging(level: int = logging.INFO) -> None:
    """Configure this service's standard console log format.

    Args:
        level: Minimum severity to emit; defaults to ``logging.INFO``.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

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
    explicit_dotenv_path = dotenv_path is not None
    if dotenv_path is None:
        # Project root is four levels above this package module.
        dotenv_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"

    base_dir = dotenv_path.resolve().parent
    if explicit_dotenv_path and not dotenv_path.is_file():
        raise FileNotFoundError(f".env not found: {dotenv_path}")

    if dotenv_path.is_file():
        load_dotenv(dotenv_path, override=False)

    def required(name: str) -> str:
        """Read a non-empty required setting from the process environment.

        Args:
            name: Environment variable name to read.

        Returns:
            The configured string value.

        Raises:
            ReferenceConfigurationError: If the setting is missing or empty.
        """
        value = os.getenv(name)
        if not value:
            raise ReferenceConfigurationError(f"Missing environment variable: {name}")
        return value

    auth_mode = os.getenv("GOOGLE_AUTH_MODE", "user").strip().lower()
    if auth_mode not in {"user", "service_account"}:
        raise ReferenceConfigurationError(
            "GOOGLE_AUTH_MODE must be either 'user' or 'service_account'"
        )

    credentials_file = None
    token_file = None
    service_account_file = None
    if auth_mode == "user":
        credentials_file = _resolve_path(required("GOOGLE_CREDENTIALS_FILE"), base_dir)
        token_file = _resolve_path(required("GOOGLE_TOKEN_FILE"), base_dir)
    else:
        service_account_file = _resolve_path(
            required("GOOGLE_SERVICE_ACCOUNT_FILE"), base_dir
        )
        oauth_credentials_path = os.getenv("GOOGLE_CREDENTIALS_FILE")
        oauth_token_path = os.getenv("GOOGLE_TOKEN_FILE")
        if oauth_credentials_path:
            credentials_file = _resolve_path(oauth_credentials_path, base_dir)
        if oauth_token_path:
            token_file = _resolve_path(oauth_token_path, base_dir)

    return Settings(
        spreadsheet_url=required("GOOGLE_SHEET_URL"),
        sheet_name=required("GOOGLE_SHEET_NAME"),
        credentials_file=credentials_file,
        token_file=token_file,
        auth_mode=auth_mode,
        service_account_file=service_account_file,
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

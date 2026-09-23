"""Command-line entry point for downloading a Google Sheet as CSV.

Usage::

    python -m app.downloader.reference.cli

or after installing the package::

    download-reference
"""

from __future__ import annotations

import logging
import sys

import gspread

from app.downloader.reference.auth import get_credentials
from app.downloader.reference.config import (
    SCOPES,
    extract_spreadsheet_id,
    load_settings,
)
from app.downloader.reference.utils import save_data_to_csv

logger = logging.getLogger(__name__)


def main() -> int:
    """Download the configured Google Sheet and save it as CSV.

    Returns:
        Exit code: ``0`` on success, non-zero on failure.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        settings = load_settings()
    except (FileNotFoundError, RuntimeError) as exc:
        logger.error("Configuration error: %s", exc)
        return 1

    spreadsheet_id = extract_spreadsheet_id(settings.spreadsheet_url)
    logger.info("Spreadsheet ID: %s", spreadsheet_id)

    try:
        credentials = get_credentials(
            settings.credentials_file,
            settings.token_file,
            SCOPES,
        )
    except FileNotFoundError as exc:
        logger.error("Credentials error: %s", exc)
        return 1

    client = gspread.authorize(credentials)
    worksheet = client.open_by_key(spreadsheet_id).worksheet(settings.sheet_name)
    data = worksheet.get_all_values()

    save_data_to_csv(settings.output_file, data)
    logger.info("Downloaded reference CSV written to: %s", settings.output_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import logging

import gspread
from app.downloader.reference.auth import get_credentials
from app.downloader.reference.config import (
    load_settings,
    SCOPES,
    extract_spreadsheet_id,
)
from utils import save_data_to_csv

logger = logging.getLogger(__name__)


def main():
    settings = load_settings()

    spreadsheet_id = extract_spreadsheet_id(settings.spreadsheet_url)

    credentials = get_credentials(
        settings.credentials_file,
        settings.token_file,
        SCOPES,
    )

    client = gspread.authorize(credentials)
    worksheet = client.open_by_key(spreadsheet_id).worksheet(settings.sheet_name)
    data = worksheet.get_all_values()
    save_data_to_csv(settings.output_file, data)

    print(f"Downloaded reference.csv written to:: {settings.output_file}")


if __name__ == "__main__":
    raise SystemExit(main())

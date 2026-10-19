"""Kafka worker that fetches Google Sheets CSV content in memory."""

import logging
from functools import partial

import gspread

from app.downloader.reference.config import (
    SCOPES,
    configure_logging,
    extract_spreadsheet_id,
    load_settings,
)
from app.downloader.reference.exceptions import ReferenceAuthenticationError
from app.downloader.reference.google_oauth import (
    get_credentials,
    get_service_account_credentials,
)
from app.downloader.reference.models import Settings
from app.downloader.reference.producer import publish_reference_csv
from app.downloader.reference.utils import serialize_data_to_csv
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.topics import REFERENCE_DOWNLOAD_REQUESTS

logger = logging.getLogger(__name__)


def handle_request(message, bus, settings: Settings | None = None) -> None:
    """Download the configured worksheet and reply with serialized CSV bytes.

    Args:
        message: Kafka request envelope with correlation and reply metadata.
        bus: Kafka bus used to publish success or failure responses.
        settings: Optional downloader settings injected once at worker startup.
    """
    try:
        if settings is None:
            settings = load_settings()
        spreadsheet_id = extract_spreadsheet_id(settings.spreadsheet_url)
        if getattr(settings, "auth_mode", "user") == "service_account":
            credentials = get_service_account_credentials(
                settings.service_account_file,
                SCOPES,
            )
            client = gspread.authorize(credentials)
            try:
                spreadsheet = client.open_by_key(spreadsheet_id)
            except PermissionError as service_account_error:
                user_credentials_file = settings.credentials_file
                user_token_file = settings.token_file
                if (
                    user_credentials_file is None
                    or user_token_file is None
                    or not user_credentials_file.is_file()
                    or not user_token_file.is_file()
                ):
                    raise ReferenceAuthenticationError(
                        "Service account cannot access the spreadsheet, and "
                        "cached user OAuth credentials are unavailable"
                    ) from service_account_error

                logger.warning(
                    "Service account cannot access the spreadsheet; "
                    "retrying with cached user OAuth credentials"
                )
                user_credentials = get_credentials(
                    user_credentials_file,
                    user_token_file,
                    SCOPES,
                )
                spreadsheet = gspread.authorize(user_credentials).open_by_key(
                    spreadsheet_id
                )
        else:
            credentials = get_credentials(
                settings.credentials_file,
                settings.token_file,
                SCOPES,
            )
            spreadsheet = gspread.authorize(credentials).open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(settings.sheet_name)
        content = serialize_data_to_csv(worksheet.get_all_values())
        publish_reference_csv(bus, message, content)
        logger.info("Reference sheet downloaded into memory (%d bytes)", len(content))
    except Exception as error:
        logger.exception("Reference spreadsheet download failed")
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the reference downloader Kafka consumer."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        REFERENCE_DOWNLOAD_REQUESTS,
        "reference-downloader-service",
        partial(handle_request, settings=settings),
        service_name="downloader_reference",
    )


if __name__ == "__main__":
    main()

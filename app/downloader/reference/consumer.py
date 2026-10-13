"""Kafka worker that fetches Google Sheets CSV content in memory."""

import logging
import os

import gspread

from app.downloader.reference.google_oauth import get_credentials
from app.downloader.reference.config import (
    SCOPES,
    extract_spreadsheet_id,
    load_settings,
)
from app.downloader.reference.producer import publish_reference_csv
from app.downloader.reference.utils import serialize_data_to_csv
from app.logging_config import configure_logging
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.topics import REFERENCE_DOWNLOAD_REQUESTS

logger = logging.getLogger(__name__)


def handle_request(message, bus) -> None:
    """Download the configured worksheet and reply with serialized CSV bytes.

    Args:
        message: Kafka request envelope with correlation and reply metadata.
        bus: Kafka bus used to publish success or failure responses.
    """
    try:
        settings = load_settings()
        spreadsheet_id = extract_spreadsheet_id(settings.spreadsheet_url)
        credentials = get_credentials(
            settings.credentials_file,
            settings.token_file,
            SCOPES,
        )
        worksheet = (
            gspread.authorize(credentials)
            .open_by_key(spreadsheet_id)
            .worksheet(settings.sheet_name)
        )
        content = serialize_data_to_csv(worksheet.get_all_values())
        publish_reference_csv(bus, message, content)
        logger.info("Reference sheet downloaded into memory (%d bytes)", len(content))
    except Exception as error:
        logger.exception("Reference spreadsheet download failed")
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the reference downloader Kafka consumer."""
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        REFERENCE_DOWNLOAD_REQUESTS,
        "reference-downloader-service",
        handle_request,
        service_name="downloader_reference",
    )


if __name__ == "__main__":
    main()

"""Kafka worker that fetches Google Sheets CSV content in memory."""

import logging
from functools import partial

import gspread

from app.downloader.reference.google_oauth import (
    get_credentials,
    get_service_account_credentials,
)
from app.downloader.reference.exceptions import ReferenceAuthenticationError
from app.downloader.reference.models import Settings
from app.downloader.reference.config import (
    SCOPES,
    configure_logging,
    extract_spreadsheet_id,
    load_settings,
)
from app.downloader.reference.producer import (
    checkpoint_completed_reference,
    publish_reference_if_changed,
)
from app.downloader.reference.utils import serialize_data_to_csv
from app.messaging.exceptions import RetryableMessageError
from app.messaging.kafka import publish_failure, run_consumer
from app.messaging.retry import is_retryable_transport_error
from app.messaging.topics import (
    REFERENCE_PIPELINE_COMPLETED,
    REFERENCE_SYNC_REQUESTS,
)

logger = logging.getLogger(__name__)


def handle_request(message, bus, settings: Settings | None = None) -> None:
    """Download the configured worksheet and publish it only when changed.

    Args:
        message: Scheduled synchronization event carrying the pipeline ID.
        bus: Kafka bus used to compare state and publish events.
        settings: Optional downloader settings injected once at worker startup.
    """
    try:
        if message.command == "pipeline_completed":
            checkpoint_completed_reference(bus, message)
            logger.info(
                "Checkpointed reference digest correlation_id=%s",
                message.correlation_id,
            )
            return
        if message.command != "sync_reference":
            raise ValueError(f"Unsupported reference command: {message.command}")
        if not message.correlation_id:
            raise ValueError("Reference sync event is missing correlation_id")
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
        changed = publish_reference_if_changed(bus, message, content)
        if changed:
            logger.info(
                "Published changed reference snapshot (%d bytes, correlation_id=%s)",
                len(content),
                message.correlation_id,
            )
        else:
            logger.info("Reference sheet is unchanged; downstream work skipped")
    except Exception as error:
        logger.exception("Reference spreadsheet download failed")
        try:
            publish_failure(bus, "downloader_reference", error, message.correlation_id)
        except Exception as publish_error:
            logger.exception("Could not publish reference downloader failure")
            raise RetryableMessageError(
                "Could not publish reference downloader failure notification"
            ) from publish_error
        if is_retryable_transport_error(error):
            raise RetryableMessageError(
                "Transient failure while downloading the reference spreadsheet"
            ) from error


def main() -> None:
    """Run the reference downloader Kafka consumer."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        [REFERENCE_SYNC_REQUESTS, REFERENCE_PIPELINE_COMPLETED],
        "reference-downloader-service",
        partial(handle_request, settings=settings),
        service_name="downloader_reference",
    )


if __name__ == "__main__":
    main()

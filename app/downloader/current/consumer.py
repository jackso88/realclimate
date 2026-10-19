"""Kafka worker that downloads current catalogue CSV content in memory."""

import logging
from functools import partial

from app.admin_auth.producer import request_session
from app.downloader.current.config import configure_logging, load_settings
from app.downloader.current.models import Settings
from app.downloader.current.queue_processor import (
    download_latest_export_content,
    delete_archive_from_admin,
    get_latest_export_cron_num,
    start_product_export,
)
from app.downloader.current.producer import publish_current_snapshot
from app.messaging.exceptions import RetryableMessageError
from app.messaging.kafka import publish_failure, run_consumer
from app.messaging.retry import is_retryable_transport_error
from app.messaging.rate_limit import rate_limit_session
from app.messaging.topics import (
    ADMIN_AUTH_CURRENT_RESPONSES,
    REFERENCE_DOWNLOADS,
)

logger = logging.getLogger(__name__)


def handle_request(message, bus, settings: Settings | None = None) -> None:
    """Download current catalogue data after a reference change event.

    Args:
        message: Reference change event containing source CSV bytes and ID.
        bus: Kafka bus used for auth requests and publication of current data.
        settings: Optional downloader settings injected once at worker startup.
    """
    try:
        if message.command != "reference_downloaded":
            raise ValueError(
                f"Unsupported current downloader command: {message.command}"
            )
        if settings is None:
            settings = load_settings()
        session = request_session(
            bus,
            ADMIN_AUTH_CURRENT_RESPONSES,
            "current-auth-rpc",
        )
        rate_limit_session(
            session,
            getattr(settings, "bootstrap_servers", "localhost:9092"),
            "downloader_current",
            "cms:account",
        )
        previous_cron_num = get_latest_export_cron_num(session, settings)
        start_product_export(session, settings)
        downloaded = download_latest_export_content(
            session,
            settings,
            after_cron_num=previous_cron_num,
        )
        delete_archive_from_admin(session, settings, downloaded.archive_filename)
        publish_current_snapshot(bus, message, downloaded)
    except Exception as error:
        logger.exception("Current catalogue download failed")
        try:
            publish_failure(bus, "downloader_current", error, message.correlation_id)
        except Exception as publish_error:
            logger.exception("Could not publish current downloader failure")
            raise RetryableMessageError(
                "Could not publish current downloader failure notification"
            ) from publish_error
        if is_retryable_transport_error(error):
            raise RetryableMessageError(
                "Transient failure while downloading the current catalogue"
            ) from error


def main() -> None:
    """Run the current downloader Kafka consumer."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        REFERENCE_DOWNLOADS,
        "current-downloader-service",
        partial(handle_request, settings=settings),
        service_name="downloader_current",
    )


if __name__ == "__main__":
    main()

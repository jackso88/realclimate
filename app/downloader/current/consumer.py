"""Kafka worker that downloads current catalogue CSV content in memory."""

import logging
import os

from app.admin_auth.producer import request_session
from app.downloader.current.config import load_settings
from app.downloader.current.queue_processor import (
    download_latest_export_content,
    delete_archive_from_admin,
    get_latest_export_cron_num,
    start_product_export,
)
from app.downloader.current.producer import publish_download, response_topic
from app.logging_config import configure_logging
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.topics import (
    ADMIN_AUTH_CURRENT_RESPONSES,
    CURRENT_DOWNLOAD_REQUESTS,
)

logger = logging.getLogger(__name__)


def handle_request(message, bus) -> None:
    """Export the latest CSV from the CMS and reply to the Kafka request.

    Args:
        message: Request envelope containing the correlation and reply data.
        bus: Kafka bus used for auth requests and the final response.
    """
    try:
        settings = load_settings()
        session = request_session(
            bus,
            ADMIN_AUTH_CURRENT_RESPONSES,
            "current-auth-rpc",
        )
        previous_cron_num = get_latest_export_cron_num(session, settings)
        start_product_export(session, settings)
        downloaded = download_latest_export_content(
            session,
            settings,
            after_cron_num=previous_cron_num,
        )
        delete_archive_from_admin(session, settings, downloaded.archive_filename)
        publish_download(bus, message, downloaded)
    except Exception as error:
        logger.exception("Current catalogue download failed")
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the current downloader Kafka consumer."""
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        CURRENT_DOWNLOAD_REQUESTS,
        "current-downloader-service",
        handle_request,
        service_name="downloader_current",
    )


if __name__ == "__main__":
    main()

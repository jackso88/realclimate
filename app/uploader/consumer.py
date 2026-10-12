"""Kafka worker that uploads and imports processed CSV content."""

import logging
import os

from app.admin_auth.producer import request_session
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.payloads import decode_bytes
from app.logging_config import configure_logging
from app.messaging.topics import ADMIN_AUTH_UPLOADER_RESPONSES, UPLOADER_REQUESTS
from app.uploader.config import load_settings
from app.uploader.queue_processor import (
    delete_uploaded_file,
    get_latest_import_cron_num,
    start_product_import,
    upload_processed_content,
    wait_for_import_completion,
)

logger = logging.getLogger(__name__)


def handle_request(message, bus) -> None:
    """Upload supplied CSV bytes, import them, and remove the admin file."""
    try:
        settings = load_settings()
        content = decode_bytes(message.payload["csv_gzip_base64"])
        filename = message.payload.get("filename", "processed.csv")
        session = request_session(
            bus,
            ADMIN_AUTH_UPLOADER_RESPONSES,
            "uploader-auth-rpc",
        )
        uploaded_file = upload_processed_content(
            session,
            settings,
            content,
            filename,
        )
        baseline_cron_num = get_latest_import_cron_num(session, settings)
        start_product_import(session, settings, uploaded_file)
        completed_task = wait_for_import_completion(
            session,
            settings,
            baseline_cron_num,
        )
        delete_uploaded_file(session, settings, uploaded_file)
        publish_reply(
            bus,
            message,
            {
                "cron_num": completed_task.cron_num,
                "file_id": uploaded_file.file_id,
            },
        )
    except Exception as error:
        logger.exception("Uploader worker failed")
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the uploader Kafka consumer."""
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        UPLOADER_REQUESTS,
        "uploader-service",
        handle_request,
    )


if __name__ == "__main__":
    main()

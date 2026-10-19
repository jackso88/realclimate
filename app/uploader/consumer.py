"""Kafka worker that imports processed catalogue events from the core."""

import logging
from functools import partial

from app.admin_auth.producer import request_session
from app.contracts.models import Envelope
from app.messaging.exceptions import RetryableMessageError
from app.messaging.kafka import publish_failure, run_consumer
from app.messaging.payloads import decode_bytes
from app.messaging.retry import is_retryable_transport_error
from app.messaging.topics import (
    ADMIN_AUTH_UPLOADER_RESPONSES,
    CORE_PROCESS_RESULTS,
    REFERENCE_PIPELINE_COMPLETED,
)
from app.uploader.config import configure_logging, load_settings
from app.uploader.models import Settings
from app.uploader.queue_processor import (
    delete_uploaded_file,
    get_latest_import_cron_num,
    start_product_import,
    upload_processed_content,
    wait_for_import_completion,
)

logger = logging.getLogger(__name__)


def handle_processed_catalogue(
    message: Envelope, bus, settings: Settings | None = None
) -> None:
    """Import changed processed data and clean up its CMS file-manager entry.

    Args:
        message: Core result event containing detailed changes and compressed
            processed CSV bytes.
        bus: Kafka bus used for requesting an authenticated admin session.
        settings: Optional uploader settings injected once at worker startup.
    """
    uploaded_file = None
    file_deleted = False
    try:
        if message.command != "catalogue_processed":
            raise ValueError(f"Unsupported uploader command: {message.command}")
        changes = message.payload.get("detailed_changes") or []
        if not changes:
            logger.info(
                "No detailed changes; upload skipped correlation_id=%s",
                message.correlation_id,
            )
            return
        if settings is None:
            settings = load_settings()
        content = decode_bytes(message.payload["processed_csv_gzip_base64"])
        session = request_session(
            bus,
            ADMIN_AUTH_UPLOADER_RESPONSES,
            "uploader-auth-rpc",
        )
        uploaded_file = upload_processed_content(
            session, settings, content, "processed.csv"
        )
        baseline_cron_num = get_latest_import_cron_num(session, settings)
        start_product_import(session, settings, uploaded_file)
        completed_task = wait_for_import_completion(
            session, settings, baseline_cron_num
        )
        delete_uploaded_file(session, settings, uploaded_file)
        file_deleted = True
        bus.publish(
            REFERENCE_PIPELINE_COMPLETED,
            Envelope.create(
                "pipeline_completed",
                {"reference_sha256": message.payload["reference_sha256"]},
                correlation_id=message.correlation_id,
            ),
            key=message.correlation_id,
        )
        logger.info(
            "Imported catalogue correlation_id=%s task=#%s file_id=%s",
            message.correlation_id,
            completed_task.cron_num,
            uploaded_file.file_id,
        )
    except Exception as error:
        logger.exception(
            "Uploader worker failed correlation_id=%s", message.correlation_id
        )
        if uploaded_file is not None and not file_deleted:
            try:
                delete_uploaded_file(session, settings, uploaded_file)
            except Exception:
                logger.exception(
                    "Could not clean up uploaded CMS file_id=%s",
                    uploaded_file.file_id,
                )
        try:
            publish_failure(bus, "uploader", error, message.correlation_id)
        except Exception as publish_error:
            logger.exception("Could not publish uploader failure")
            raise RetryableMessageError(
                "Could not publish uploader failure notification"
            ) from publish_error
        if is_retryable_transport_error(error):
            raise RetryableMessageError(
                "Transient failure while importing the processed catalogue"
            ) from error


def main() -> None:
    """Run the uploader Kafka consumer subscribed to core result events."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        CORE_PROCESS_RESULTS,
        "uploader-service",
        partial(handle_processed_catalogue, settings=settings),
        service_name="uploader",
    )


if __name__ == "__main__":
    main()

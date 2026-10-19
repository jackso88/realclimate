"""Kafka worker that processes supplied catalogue data and returns results."""

import logging
from functools import partial

from app.core.config import CoreSettings, configure_logging, load_settings
from app.core.duplicate_mapping import DUPLICATE_CODE_MAP
from app.core.pipeline import (
    decode_duplicate_map,
    encode_duplicate_map,
    process_catalogue,
)
from app.messaging.kafka import publish_failure, publish_reply, run_consumer
from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes, encode_bytes
from app.messaging.topics import (
    CORE_DUPLICATE_MAP_STATE,
    CORE_NOTIFICATIONS,
    CORE_PROCESS_REQUESTS,
    CORE_PROCESS_RESULTS,
)

logger = logging.getLogger(__name__)


def handle_process(
    message: Envelope, bus, settings: CoreSettings | None = None
) -> None:
    """Process caller-supplied source CSVs and publish the core result.

    The core no longer downloads inputs or invokes the uploader. It emits a
    result event for downstream consumers, which provides an extension point
    for an analytics service.

    Args:
        message: Request containing compressed reference and current CSVs.
        bus: Kafka bus used to read and persist duplicate state and publish
            result, notification, and response messages.
        settings: Optional core settings injected once at worker startup.
    """
    try:
        if message.command != "process_catalogue":
            raise ValueError(f"Unsupported core command: {message.command}")
        reference_csv = decode_bytes(message.payload["reference_csv_gzip_base64"])
        current_csv = decode_bytes(message.payload["current_csv_gzip_base64"])
        reference_sha256 = message.payload.get("reference_sha256")
        latest_state = bus.read_latest(CORE_DUPLICATE_MAP_STATE)
        duplicate_map = (
            decode_duplicate_map(latest_state.payload)
            if latest_state
            else dict(DUPLICATE_CODE_MAP)
        )
        output = process_catalogue(reference_csv, current_csv, duplicate_map)

        if settings is None:
            settings = load_settings()
        excluded_path = settings.excluded_csv_path
        excluded_path.parent.mkdir(parents=True, exist_ok=True)
        excluded_path.write_bytes(output.excluded_csv)

        bus.publish(
            CORE_DUPLICATE_MAP_STATE,
            Envelope.create(
                "duplicate_map_state",
                encode_duplicate_map(output.updated_duplicate_map),
            ),
            key="duplicate-map",
        )
        changes = output.detailed_changes
        result_payload = {
            "reference_sha256": reference_sha256,
            "processed_csv_gzip_base64": encode_bytes(output.processed_csv),
            "detailed_changes": changes,
            "changes_count": len(changes),
        }
        bus.publish(
            CORE_PROCESS_RESULTS,
            Envelope.create(
                "catalogue_processed",
                result_payload,
                correlation_id=message.correlation_id,
            ),
            key=message.correlation_id,
        )
        if changes:
            bus.publish(
                CORE_NOTIFICATIONS,
                Envelope.create(
                    "detailed_changes",
                    {"changes": changes},
                    correlation_id=message.correlation_id,
                ),
            )

        logger.info("Core processing completed: %d detailed changes", len(changes))
    except Exception as error:
        logger.exception("Core catalogue processing failed")
        publish_failure(bus, "core", error)
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the core data-processing Kafka consumer."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        CORE_PROCESS_REQUESTS,
        "core-service",
        partial(handle_process, settings=settings),
        service_name="core",
    )


if __name__ == "__main__":
    main()

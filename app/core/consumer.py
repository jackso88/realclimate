"""Kafka worker that joins downloader events through Redis and processes them."""

import logging
from functools import partial
from uuid import uuid4

from app.contracts.models import Envelope
from app.core.config import configure_logging, load_settings
from app.core.duplicate_mapping import DUPLICATE_CODE_MAP
from app.core.models import CoreSettings
from app.core.pending_inputs import RedisPendingInputsStore
from app.core.redis_client import RedisClient, RedisCommandError
from app.core.pipeline import (
    decode_duplicate_map,
    encode_duplicate_map,
    process_catalogue,
)
from app.messaging.kafka import publish_failure, run_consumer
from app.messaging.exceptions import RetryableMessageError
from app.messaging.payloads import decode_bytes, encode_bytes
from app.messaging.topics import (
    CORE_DUPLICATE_MAP_STATE,
    CORE_NOTIFICATIONS,
    CORE_PROCESS_RESULTS,
    CURRENT_DOWNLOADS,
    REFERENCE_DOWNLOADS,
    REFERENCE_PIPELINE_COMPLETED,
)

logger = logging.getLogger(__name__)
CORE_INPUT_TOPICS = [REFERENCE_DOWNLOADS, CURRENT_DOWNLOADS]


def handle_process(
    message: Envelope,
    bus,
    settings: CoreSettings | None = None,
    pending_inputs: RedisPendingInputsStore | None = None,
) -> None:
    """Collect one downloader result and process the pair when both are ready.

    Each downloader sends a separate compressed CSV event. The event's
    correlation ID keys its part in Redis. Redis atomically grants a lease when
    both parts exist, preventing two core instances from processing the same
    pair concurrently. A successfully handled Kafka event is committed by the
    consumer. Redis transport and command failures become retryable Kafka
    errors; other processing failures are reported and treated as non-retryable.

    Args:
        message: Reference or current downloader completion event.
        bus: Kafka bus for duplicate state, results, and notifications.
        settings: Validated core configuration loaded once at worker startup.
        pending_inputs: Redis-backed storage for incomplete downloader pairs.

    Raises:
        ValueError: If the event contract is malformed or unsupported.
        RetryableMessageError: If Redis is unavailable or rejects a command,
            so Kafka can redeliver the event.
        Exception: If input processing or publication fails.
    """
    claimed = False
    claim_token = str(uuid4())
    correlation_id = message.correlation_id
    try:
        if not correlation_id:
            raise ValueError("Downloader event is missing correlation_id")
        if settings is None:
            settings = load_settings()
        if pending_inputs is None:
            pending_inputs = create_pending_inputs_store(settings)
        if pending_inputs.is_completed(correlation_id):
            logger.info(
                "Ignoring duplicate completed input correlation_id=%s",
                correlation_id,
            )
            return

        if message.command == "reference_downloaded":
            content = decode_bytes(message.payload["reference_csv_gzip_base64"])
            digest = message.payload["reference_sha256"]
            claimed = pending_inputs.save_reference(
                correlation_id, content, digest, claim_token
            )
        elif message.command == "current_downloaded":
            content = decode_bytes(message.payload["current_csv_gzip_base64"])
            claimed = pending_inputs.save_current(correlation_id, content, claim_token)
        else:
            raise ValueError(f"Unsupported core command: {message.command}")

        if not claimed:
            logger.info(
                "Stored %s input; waiting for its correlated partner "
                "correlation_id=%s",
                message.command,
                correlation_id,
            )
            return

        reference_csv, current_csv, reference_sha256 = pending_inputs.get_pair(
            correlation_id
        )
        latest_state = bus.read_latest(CORE_DUPLICATE_MAP_STATE)
        duplicate_map = (
            decode_duplicate_map(latest_state.payload)
            if latest_state
            else dict(DUPLICATE_CODE_MAP)
        )
        output = process_catalogue(reference_csv, current_csv, duplicate_map)

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
            "detailed_changes": changes,
            "changes_count": len(changes),
        }
        if changes:
            result_payload["processed_csv_gzip_base64"] = encode_bytes(
                output.processed_csv
            )
        bus.publish(
            CORE_PROCESS_RESULTS,
            Envelope.create(
                "catalogue_processed",
                result_payload,
                correlation_id=correlation_id,
            ),
            key=correlation_id,
        )
        if changes:
            bus.publish(
                CORE_NOTIFICATIONS,
                Envelope.create(
                    "detailed_changes",
                    {"changes": changes},
                    correlation_id=correlation_id,
                ),
            )
        else:
            bus.publish(
                REFERENCE_PIPELINE_COMPLETED,
                Envelope.create(
                    "pipeline_completed",
                    {"reference_sha256": reference_sha256},
                    correlation_id=correlation_id,
                ),
                key=correlation_id,
            )
        if not pending_inputs.complete(correlation_id, claim_token):
            raise RuntimeError(
                f"Lost Redis processing lease for correlation_id={correlation_id}"
            )
        claimed = False
        logger.info(
            "Core processing completed correlation_id=%s: %d detailed changes",
            correlation_id,
            len(changes),
        )
    except Exception as error:
        logger.exception("Core catalogue processing failed")
        try:
            publish_failure(bus, "core", error, correlation_id)
        finally:
            if claimed and pending_inputs is not None and correlation_id:
                try:
                    pending_inputs.release(correlation_id, claim_token)
                except Exception:
                    logger.exception(
                        "Could not release Redis claim correlation_id=%s",
                        correlation_id,
                    )
        if isinstance(error, (OSError, RedisCommandError)):
            raise RetryableMessageError(
                "Redis failed while storing or retrieving correlated core inputs"
            ) from error
        raise


def create_pending_inputs_store(settings: CoreSettings) -> RedisPendingInputsStore:
    """Create the Redis input store using validated core settings.

    Args:
        settings: Core settings containing Redis URL and expiry values.

    Returns:
        A Redis-backed store configured for this core worker.
    """
    client = RedisClient.from_url(settings.pending_redis_url)
    return RedisPendingInputsStore(
        client,
        ttl_seconds=settings.pending_input_ttl_seconds,
        claim_ttl_seconds=settings.processing_claim_ttl_seconds,
    )


def main() -> None:
    """Run the core Kafka consumer with one Redis store per worker process."""
    configure_logging()
    settings = load_settings()
    pending_inputs = create_pending_inputs_store(settings)
    try:
        run_consumer(
            settings.bootstrap_servers,
            CORE_INPUT_TOPICS,
            "core-service",
            partial(
                handle_process,
                settings=settings,
                pending_inputs=pending_inputs,
            ),
            service_name="core",
        )
    finally:
        pending_inputs.client.close()


if __name__ == "__main__":
    main()

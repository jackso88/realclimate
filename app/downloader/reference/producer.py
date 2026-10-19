"""Publish changed reference snapshots as Kafka events."""

import hashlib

from app.contracts.models import Envelope
from app.messaging.kafka import KafkaBus
from app.messaging.payloads import encode_bytes
from app.messaging.topics import REFERENCE_DOWNLOADS, REFERENCE_SNAPSHOT_STATE


def publish_reference_if_changed(
    bus: KafkaBus, request: Envelope, content: bytes
) -> bool:
    """Publish a new reference snapshot only when its bytes have changed.

    Args:
        bus: Kafka producer and compacted-state reader.
        request: Scheduled synchronization event carrying the pipeline ID.
        content: Serialized CSV bytes downloaded from Google Sheets.

    Returns:
        ``True`` when a changed snapshot was published, otherwise ``False``.
    """
    digest = hashlib.sha256(content).hexdigest()
    latest = bus.read_latest(REFERENCE_SNAPSHOT_STATE)
    if latest and latest.payload.get("sha256") == digest:
        return False

    bus.publish(
        REFERENCE_DOWNLOADS,
        Envelope.create(
            "reference_downloaded",
            {
                "reference_sha256": digest,
                "reference_csv_gzip_base64": encode_bytes(content),
            },
            correlation_id=request.correlation_id,
        ),
        key=request.correlation_id,
    )
    return True


def checkpoint_completed_reference(bus: KafkaBus, completion_event: Envelope) -> None:
    """Persist the reference digest after the full pipeline succeeds.

    Args:
        bus: Kafka producer used to write the compacted fingerprint state.
        completion_event: Completion event containing a digest and correlation ID.
    """
    if completion_event.command != "pipeline_completed":
        raise ValueError(
            f"Unsupported reference completion command: {completion_event.command}"
        )
    digest = completion_event.payload.get("reference_sha256")
    if not isinstance(digest, str) or not digest:
        raise ValueError("Pipeline completion is missing reference_sha256")
    bus.publish(
        REFERENCE_SNAPSHOT_STATE,
        Envelope.create(
            "reference_snapshot_state",
            {"sha256": digest},
            correlation_id=completion_event.correlation_id,
        ),
        key="reference-snapshot",
    )

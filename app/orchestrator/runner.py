"""Run the change-driven catalogue workflow across service contracts."""

import hashlib
import logging

from app.messaging.kafka import KafkaBus
from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes, encode_bytes
from app.messaging.topics import (
    CORE_PROCESS_REQUESTS,
    CORE_PROCESS_RESULTS,
    CURRENT_DOWNLOAD_REQUESTS,
    CURRENT_DOWNLOAD_RESPONSES,
    ORCHESTRATOR_UPLOADER_RESPONSES,
    ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE,
    REFERENCE_DOWNLOAD_REQUESTS,
    REFERENCE_DOWNLOAD_RESPONSES,
    UPLOADER_REQUESTS,
)
from app.orchestrator.models import OrchestratorSettings

logger = logging.getLogger(__name__)
REFERENCE_STATE_KEY = "reference-fingerprint"


def run_workflow(bus: KafkaBus, settings: OrchestratorSettings) -> dict:
    """Run downstream work only after the reference input changes.

    The reference downloader runs first. A changed reference snapshot triggers
    current download and core processing. Uploader is called only when core
    reports detailed changes. The durable reference checkpoint is written only
    after all required downstream work succeeds, allowing failed runs to retry.

    Args:
        bus: Kafka client used for RPCs, state reads, and checkpoint writes.
        settings: Timeouts and worker identity for RPC response groups.

    Returns:
        Workflow status, reference digest, and whether importing was done.

    Raises:
        RemoteServiceError: If a called service replies with a failure.
        RequestTimeoutError: If a called service does not reply in time.
        RuntimeError: If a reply payload is malformed or Kafka state access fails.
    """
    reference_response = bus.request(
        REFERENCE_DOWNLOAD_REQUESTS,
        REFERENCE_DOWNLOAD_RESPONSES,
        "download_csv",
        {},
        timeout=settings.request_timeout_seconds,
        response_group=f"{settings.instance_id}-reference-rpc",
    )
    reference_csv = decode_bytes(reference_response.payload["csv_gzip_base64"])
    reference_digest = hashlib.sha256(reference_csv).hexdigest()
    current_state = bus.read_latest(ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE)
    previous_digest = current_state.payload.get("sha256") if current_state else None

    if reference_digest == previous_digest:
        logger.info("Reference CSV is unchanged; skipping current download and core")
        return {
            "status": "skipped",
            "reason": "reference_unchanged",
            "reference_sha256": reference_digest,
            "uploaded": False,
        }

    current_response = bus.request(
        CURRENT_DOWNLOAD_REQUESTS,
        CURRENT_DOWNLOAD_RESPONSES,
        "download_csv",
        {},
        timeout=settings.request_timeout_seconds,
        response_group=f"{settings.instance_id}-current-rpc",
    )
    current_csv = decode_bytes(current_response.payload["csv_gzip_base64"])
    core_response = bus.request(
        CORE_PROCESS_REQUESTS,
        CORE_PROCESS_RESULTS,
        "process_catalogue",
        {
            "reference_csv_gzip_base64": encode_bytes(reference_csv),
            "current_csv_gzip_base64": encode_bytes(current_csv),
            "reference_sha256": reference_digest,
        },
        timeout=settings.request_timeout_seconds,
        response_group=f"{settings.instance_id}-core-rpc",
    )

    detailed_changes = core_response.payload["detailed_changes"]
    if not isinstance(detailed_changes, list):
        raise ValueError("Core detailed_changes must be a list")
    uploaded = False
    if detailed_changes:
        processed_csv = decode_bytes(core_response.payload["processed_csv_gzip_base64"])
        bus.request(
            UPLOADER_REQUESTS,
            ORCHESTRATOR_UPLOADER_RESPONSES,
            "import_processed_csv",
            {
                "filename": "processed.csv",
                "csv_gzip_base64": encode_bytes(processed_csv),
            },
            timeout=settings.uploader_timeout_seconds,
            response_group=f"{settings.instance_id}-uploader-rpc",
        )
        uploaded = True

    bus.publish(
        ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE,
        Envelope.create("reference_fingerprint", {"sha256": reference_digest}),
        key=REFERENCE_STATE_KEY,
    )
    logger.info(
        "Workflow completed for reference %s: %d changes, uploaded=%s",
        reference_digest,
        len(detailed_changes),
        uploaded,
    )
    return {
        "status": "processed",
        "reference_sha256": reference_digest,
        "changes_count": len(detailed_changes),
        "uploaded": uploaded,
    }

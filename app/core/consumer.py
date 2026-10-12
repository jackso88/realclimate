"""Kafka worker for the complete in-memory catalogue update."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core.models import DuplicateMap
from app.core.duplicate_mapping import DUPLICATE_CODE_MAP
from app.core.pipeline import (
    decode_duplicate_map,
    encode_duplicate_map,
    process_catalogue,
)
from app.downloader.current.producer import response_topic as current_response_topic
from app.downloader.reference.producer import response_topic as reference_response_topic
from app.logging_config import configure_logging
from app.messaging.kafka import (
    KafkaBus,
    publish_failure,
    publish_reply,
    run_consumer,
)
from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes
from app.messaging.topics import (
    CORE_NOTIFICATIONS,
    CORE_DUPLICATE_MAP_STATE,
    CORE_RUNS,
    CORE_CURRENT_RESPONSES,
    CORE_REFERENCE_RESPONSES,
    CORE_UPLOADER_RESPONSES,
    CURRENT_DOWNLOAD_REQUESTS,
    REFERENCE_DOWNLOAD_REQUESTS,
)
from app.uploader.producer import request_import

logger = logging.getLogger(__name__)
duplicate_map_cache: DuplicateMap | None = None


def _download(bus: KafkaBus, topic: str, response_topic: str, group: str) -> bytes:
    response = bus.request(
        topic,
        response_topic,
        "download_csv",
        {},
        timeout=float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "900")),
        response_group=group,
    )
    return decode_bytes(response.payload["csv_gzip_base64"])


def handle_run(message: Envelope, bus: KafkaBus) -> None:
    """Download both inputs concurrently, process, import, then notify."""
    global duplicate_map_cache
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            current_future = pool.submit(
                _download,
                bus,
                CURRENT_DOWNLOAD_REQUESTS,
                current_response_topic(),
                CORE_CURRENT_RESPONSES,
            )
            reference_future = pool.submit(
                _download,
                bus,
                REFERENCE_DOWNLOAD_REQUESTS,
                reference_response_topic(),
                CORE_REFERENCE_RESPONSES,
            )
            current_content = current_future.result()
            reference_content = reference_future.result()

        output = process_catalogue(
            reference_content,
            current_content,
            duplicate_map_cache,
        )
        excluded_path = Path(
            os.getenv(
                "EXCLUDED_CSV_PATH",
                "/app/storage/outputs/for_zalivka_excluded.csv",
            )
        )
        excluded_path.parent.mkdir(parents=True, exist_ok=True)
        excluded_path.write_bytes(output.excluded_csv)

        response = request_import(
            bus,
            CORE_UPLOADER_RESPONSES,
            CORE_UPLOADER_RESPONSES,
            output.processed_csv,
            timeout=float(os.getenv("IMPORT_TIMEOUT_SECONDS", "1800")),
        )
        bus.publish(
            CORE_DUPLICATE_MAP_STATE,
            Envelope.create(
                "duplicate_map_state",
                encode_duplicate_map(output.updated_duplicate_map),
            ),
            key="duplicate-map",
        )
        duplicate_map_cache = output.updated_duplicate_map
        if output.detailed_changes:
            bus.publish(
                CORE_NOTIFICATIONS,
                Envelope.create(
                    "detailed_changes",
                    {"changes": output.detailed_changes},
                ),
            )
        publish_reply(bus, message, {"import": response.payload})
        logger.info(
            "Catalogue run completed: %d detail lines", len(output.detailed_changes)
        )
    except Exception as error:
        logger.exception("Core catalogue run failed")
        publish_failure(bus, "core", error)
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the core Kafka consumer."""
    configure_logging()
    bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    state_bus = KafkaBus(bootstrap_servers)
    latest_state = state_bus.read_latest(CORE_DUPLICATE_MAP_STATE)
    global duplicate_map_cache
    duplicate_map_cache = (
        decode_duplicate_map(latest_state.payload)
        if latest_state
        else dict(DUPLICATE_CODE_MAP)
    )
    logger.info(
        "Loaded %d duplicate map entries from Kafka state", len(duplicate_map_cache)
    )
    run_consumer(
        bootstrap_servers,
        CORE_RUNS,
        "core-service",
        handle_run,
    )


if __name__ == "__main__":
    main()

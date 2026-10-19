"""Kafka consumer for change-driven workflow requests."""

import logging
import os

from app.messaging.kafka import (
    DEFAULT_MAX_POLL_INTERVAL_MS,
    publish_failure,
    publish_reply,
    run_consumer,
)
from app.messaging.topics import ORCHESTRATOR_RUNS
from app.orchestrator.config import configure_logging, load_settings
from app.orchestrator.models import OrchestratorSettings
from app.orchestrator.runner import run_workflow

logger = logging.getLogger(__name__)

# Extra time on top of the worst-case run before Kafka may evict the consumer.
POLL_INTERVAL_MARGIN_SECONDS = 600


def max_poll_interval_ms(settings: OrchestratorSettings) -> int:
    """Return the poll interval this worker needs to survive a slow run.

    The orchestrator handles one run per message and does not poll Kafka while
    it works. If a run outlasted ``max.poll.interval.ms``, Kafka would evict the
    consumer, the offset commit would fail, and the same run could start again.

    Args:
        settings: Step timeouts that bound the length of one run.

    Returns:
        The worst-case run time plus a safety margin, in milliseconds, and never
        less than the library default.
    """
    needed_seconds = settings.worst_case_run_seconds + POLL_INTERVAL_MARGIN_SECONDS
    return max(DEFAULT_MAX_POLL_INTERVAL_MS, needed_seconds * 1000)


def handle_run(message, bus) -> None:
    """Execute the workflow and return its outcome to the requester.

    Args:
        message: Request envelope containing reply metadata.
        bus: Kafka bus used by the workflow services and response publisher.
    """
    try:
        result = run_workflow(bus, load_settings())
        logger.info(
            "Orchestrated workflow completed: status=%s, reason=%s, changes=%s, uploaded=%s",
            result.get("status", "unknown"),
            result.get("reason", "none"),
            result.get("changes_count", 0),
            result.get("uploaded", False),
        )
        publish_reply(bus, message, result)
    except Exception as error:
        logger.exception("Orchestrated catalogue workflow failed")
        publish_failure(bus, "orchestrator", error)
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Start the workflow orchestration Kafka worker.

    Raises:
        ValueError: If a timeout setting is not a positive integer. The worker
            needs the timeouts at startup to size its Kafka poll interval, so a
            bad value stops it immediately instead of failing the first run.
    """
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        ORCHESTRATOR_RUNS,
        "orchestrator-service",
        handle_run,
        service_name="orchestrator",
        max_poll_interval_ms=max_poll_interval_ms(load_settings()),
    )


if __name__ == "__main__":
    main()

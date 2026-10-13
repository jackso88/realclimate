"""Kafka consumer for change-driven workflow requests."""

import logging
import os

from app.messaging.kafka import publish_failure, publish_reply, run_consumer
from app.messaging.topics import ORCHESTRATOR_RUNS
from app.orchestrator.config import configure_logging, load_settings
from app.orchestrator.runner import run_workflow

logger = logging.getLogger(__name__)


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
    """Start the workflow orchestration Kafka worker."""
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        ORCHESTRATOR_RUNS,
        "orchestrator-service",
        handle_run,
        service_name="orchestrator",
    )


if __name__ == "__main__":
    main()

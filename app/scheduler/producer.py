"""Publish scheduled workflow requests to Kafka."""

import logging
import os

from app.messaging.kafka import KafkaBus
from app.messaging.topics import ORCHESTRATOR_RUNS, ORCHESTRATOR_RUN_RESPONSES

logger = logging.getLogger(__name__)


def publish_workflow_run() -> None:
    """Start a change-driven workflow and wait for its completion response."""
    bus = KafkaBus(os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    logger.info("Starting scheduled catalogue workflow")
    response = bus.request(
        ORCHESTRATOR_RUNS,
        ORCHESTRATOR_RUN_RESPONSES,
        "run_workflow",
        {"source": "scheduler"},
        timeout=float(os.getenv("ORCHESTRATOR_RUN_TIMEOUT_SECONDS", "5400")),
        response_group="scheduler-orchestrator-rpc",
    )
    result = response.payload or {}
    logger.info(
        "Scheduled catalogue workflow completed: status=%s, reason=%s, "
        "changes=%s, uploaded=%s",
        result.get("status", "unknown"),
        result.get("reason", "none"),
        result.get("changes_count", 0),
        result.get("uploaded", False),
    )

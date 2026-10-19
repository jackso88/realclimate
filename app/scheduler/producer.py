"""Publish scheduled workflow requests to Kafka."""

import logging

from app.messaging.kafka import KafkaBus
from app.messaging.topics import ORCHESTRATOR_RUN_RESPONSES, ORCHESTRATOR_RUNS
from app.scheduler.config import load_settings
from app.scheduler.models import SchedulerSettings

logger = logging.getLogger(__name__)


def publish_workflow_run(settings: SchedulerSettings | None = None) -> None:
    """Start a workflow, reusing scheduler settings when provided.

    Args:
        settings: Settings loaded at daemon startup. Direct calls load the
            configuration on demand.
    """
    if settings is None:
        settings = load_settings()
    bus = KafkaBus(settings.bootstrap_servers)
    logger.info("Starting scheduled catalogue workflow")
    response = bus.request(
        ORCHESTRATOR_RUNS,
        ORCHESTRATOR_RUN_RESPONSES,
        "run_workflow",
        {"source": "scheduler"},
        timeout=settings.orchestrator_timeout_seconds,
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

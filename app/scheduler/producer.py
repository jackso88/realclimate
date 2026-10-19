"""Publish scheduled reference synchronization events to Kafka."""

import logging
from uuid import uuid4

from app.messaging.kafka import KafkaBus
from app.contracts.models import Envelope
from app.messaging.topics import REFERENCE_SYNC_REQUESTS
from app.scheduler.config import load_settings
from app.scheduler.models import SchedulerSettings

logger = logging.getLogger(__name__)


def publish_reference_sync(settings: SchedulerSettings | None = None) -> str:
    """Publish a reference synchronization request for the scheduled run.

    Args:
        settings: Scheduler settings loaded at daemon startup. Direct calls
            load configuration on demand.

    Returns:
        The correlation ID assigned to this synchronization pipeline.
    """
    if settings is None:
        settings = load_settings()
    bus = KafkaBus(settings.bootstrap_servers)
    correlation_id = str(uuid4())
    bus.publish(
        REFERENCE_SYNC_REQUESTS,
        Envelope.create(
            "sync_reference",
            {"source": "scheduler"},
            correlation_id=correlation_id,
        ),
        key=correlation_id,
    )
    logger.info("Published reference sync request correlation_id=%s", correlation_id)
    return correlation_id

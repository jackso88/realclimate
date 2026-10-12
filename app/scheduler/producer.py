"""Publish scheduled core runs to Kafka."""

import os

from app.messaging.kafka import KafkaBus
from app.messaging.topics import CORE_RUN_RESPONSES, CORE_RUNS


def publish_core_run() -> None:
    """Run the core pipeline and wait for its completion response."""
    bus = KafkaBus(os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
    bus.request(
        CORE_RUNS,
        CORE_RUN_RESPONSES,
        "run_catalogue",
        {"source": "scheduler"},
        timeout=float(os.getenv("CORE_RUN_TIMEOUT_SECONDS", "3600")),
        response_group="scheduler-core-rpc",
    )

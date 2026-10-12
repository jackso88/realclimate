"""Kafka producer, consumer, request/reply, and worker helpers."""

import logging
import re
from time import monotonic
from typing import Callable
from uuid import uuid4

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confluent_kafka import Consumer, Producer

from app.messaging.exceptions import (
    RemoteServiceError,
    RequestTimeoutError,
)
from app.messaging.models import Envelope
from app.messaging.topics import CORE_NOTIFICATIONS

logger = logging.getLogger(__name__)
SENSITIVE_QUERY_VALUE = re.compile(r"(?i)(access|token|password)=([^&\s]+)")


def sanitize_error(message: str) -> str:
    """Redact common credential parameters before logging or notification."""
    return SENSITIVE_QUERY_VALUE.sub(r"\1=<redacted>", message)


class KafkaBus:
    """Thin Kafka wrapper shared by producers and request/reply consumers."""

    def __init__(self, bootstrap_servers: str):
        from confluent_kafka import Producer

        self.bootstrap_servers = bootstrap_servers
        self.producer = Producer(
            {
                "bootstrap.servers": bootstrap_servers,
                "message.max.bytes": 80_000_000,
            }
        )

    def publish(self, topic: str, message: Envelope, key: str | None = None) -> None:
        """Publish an envelope and wait for broker acknowledgement."""
        self.producer.produce(
            topic,
            key=key.encode("utf-8") if key else None,
            value=message.encode(),
        )
        self.producer.poll(0)
        remaining = self.producer.flush(10)
        if remaining:
            raise RuntimeError(f"Kafka did not acknowledge message for {topic}")

    def read_latest(self, topic: str, partition: int = 0) -> Envelope | None:
        """Read the newest Kafka record in a one-partition compacted state topic."""
        from confluent_kafka import Consumer, TopicPartition

        consumer = Consumer(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": f"state-reader-{uuid4()}",
                "enable.auto.commit": False,
                "auto.offset.reset": "latest",
            }
        )
        try:
            low, high = consumer.get_watermark_offsets(
                TopicPartition(topic, partition), timeout=10
            )
            if high <= low:
                return None
            consumer.assign([TopicPartition(topic, partition, high - 1)])
            message = consumer.poll(10)
            if message is None:
                return None
            if message.error():
                raise RuntimeError(message.error().str())
            return Envelope.decode(message.value())
        finally:
            consumer.close()

    def request(
        self,
        request_topic: str,
        response_topic: str,
        command: str,
        payload: dict,
        *,
        timeout: float = 120,
        response_group: str,
    ) -> Envelope:
        """Send a request and wait for a response with its correlation ID."""
        from confluent_kafka import Consumer, KafkaError

        correlation_id = str(uuid4())
        consumer = Consumer(
            {
                "bootstrap.servers": self.bootstrap_servers,
                "group.id": response_group,
                "enable.auto.commit": False,
                "auto.offset.reset": "latest",
                "max.partition.fetch.bytes": 80_000_000,
                "max.poll.interval.ms": 3_600_000,
            }
        )
        consumer.subscribe([response_topic])
        try:
            assignment_deadline = monotonic() + min(timeout, 15)
            while not consumer.assignment() and monotonic() < assignment_deadline:
                consumer.poll(0.1)

            request_message = Envelope.create(
                command,
                payload,
                correlation_id=correlation_id,
                reply_to=response_topic,
            )
            self.publish(request_topic, request_message, key=correlation_id)

            deadline = monotonic() + timeout
            while monotonic() < deadline:
                kafka_message = consumer.poll(min(1.0, deadline - monotonic()))
                if kafka_message is None:
                    continue
                if kafka_message.error():
                    if kafka_message.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise RuntimeError(kafka_message.error().str())
                response = Envelope.decode(kafka_message.value())
                if response.correlation_id != correlation_id:
                    continue
                if response.error:
                    raise RemoteServiceError(sanitize_error(response.error))
                return response
            raise RequestTimeoutError(
                f"Timed out waiting for {response_topic} response to {command}"
            )
        finally:
            consumer.close()


def run_consumer(
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    handler: Callable[[Envelope, KafkaBus], None],
) -> None:
    """Consume envelopes forever and commit each handled Kafka record."""
    from confluent_kafka import Consumer, KafkaError

    bus = KafkaBus(bootstrap_servers)
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "max.partition.fetch.bytes": 80_000_000,
            "max.poll.interval.ms": 3_600_000,
        }
    )
    consumer.subscribe([topic])
    logger.info("Kafka consumer subscribed to %s", topic)
    try:
        while True:
            kafka_message = consumer.poll(1.0)
            if kafka_message is None:
                continue
            if kafka_message.error():
                if kafka_message.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise RuntimeError(kafka_message.error().str())

            envelope = Envelope.decode(kafka_message.value())
            try:
                handler(envelope, bus)
            except Exception:
                logger.exception("Unhandled message failure on topic %s", topic)
            finally:
                consumer.commit(message=kafka_message, asynchronous=False)
    finally:
        consumer.close()


def publish_reply(
    bus: KafkaBus,
    request: Envelope,
    payload: dict | None = None,
    error: str | None = None,
) -> None:
    """Reply to a request when it includes a response topic."""
    if not request.reply_to:
        return
    reply = Envelope.create(
        "response",
        payload,
        correlation_id=request.correlation_id,
        error=sanitize_error(error) if error else None,
    )
    bus.publish(request.reply_to, reply, key=request.correlation_id)


def publish_failure(
    bus: KafkaBus,
    service: str,
    error: Exception,
) -> None:
    """Publish a redacted failure notification to the notification service."""
    payload = {
        "service": service,
        "error_type": type(error).__name__,
        "error": sanitize_error(str(error)),
    }
    bus.publish(CORE_NOTIFICATIONS, Envelope.create("failure", payload))

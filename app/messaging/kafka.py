"""Kafka producer, consumer, request/reply, and worker helpers."""

import logging
import re
from time import monotonic
from typing import TYPE_CHECKING, Callable
from uuid import uuid4

if TYPE_CHECKING:
    from confluent_kafka import Consumer, Producer

from app.messaging.config import load_client_settings
from app.messaging.exceptions import (
    RemoteServiceError,
    RequestTimeoutError,
)
from app.messaging.models import Envelope
from app.messaging.topics import CORE_NOTIFICATIONS

logger = logging.getLogger(__name__)
SENSITIVE_QUERY_VALUE = re.compile(r"(?i)(access|token|password)=([^&\s]+)")


def sanitize_error(message: str) -> str:
    """Redact common credential query parameters from an error string.

    Args:
        message: Error text that may contain access tokens, passwords, or
            other sensitive query values.

    Returns:
        Error text with recognized secret values replaced by ``<redacted>``.
    """
    return SENSITIVE_QUERY_VALUE.sub(r"\1=<redacted>", message)


class KafkaBus:
    """Thin Kafka wrapper shared by producers and request/reply consumers."""

    def __init__(self, bootstrap_servers: str):
        """Create a producer connected to the configured Kafka brokers.

        Args:
            bootstrap_servers: Comma-separated broker address list accepted
                by ``confluent-kafka``.
        """
        from confluent_kafka import Producer

        self.bootstrap_servers = bootstrap_servers
        self.client_configuration = load_client_settings(bootstrap_servers).to_dict()
        self.producer = Producer(
            {
                **self.client_configuration,
                "message.max.bytes": 80_000_000,
            }
        )

    def publish(self, topic: str, message: Envelope, key: str | None = None) -> None:
        """Publish an envelope and wait for broker delivery to complete.

        Args:
            topic: Kafka topic that receives the serialized envelope.
            message: Envelope to serialize and publish.
            key: Optional partitioning key; messages with the same key are
                routed consistently by Kafka.

        Raises:
            RuntimeError: If the producer cannot finish delivery within the
                acknowledgement wait period.
            KafkaException: If the producer rejects the message or encounters
                a broker error.
        """
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
        """Read the newest record from a compacted Kafka state topic.

        Args:
            topic: Name of the state topic to read.
            partition: Partition number to inspect; defaults to partition zero.

        Returns:
            The last envelope in the partition, or ``None`` when it is empty.

        Raises:
            RuntimeError: If Kafka reports an error while reading the record.
            KafkaException: If the topic or requested partition is unavailable.
        """
        from confluent_kafka import Consumer, TopicPartition

        consumer = Consumer(
            {
                **self.client_configuration,
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
        """Publish a request and wait for its correlated response.

        Args:
            request_topic: Topic consumed by the target service.
            response_topic: Topic on which the response is expected.
            command: Operation name sent in the request envelope.
            payload: JSON-serializable request data.
            timeout: Maximum total wait for a matching response, in seconds.
            response_group: Consumer group used for the response subscription.

        Returns:
            The response envelope matching the generated correlation ID.

        Raises:
            RemoteServiceError: If the target service returns an error.
            RequestTimeoutError: If a matching response does not arrive in time.
            RuntimeError: If Kafka reports an error while consuming.
        """
        from confluent_kafka import Consumer, KafkaError

        correlation_id = str(uuid4())
        consumer = Consumer(
            {
                **self.client_configuration,
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
    *,
    service_name: str | None = None,
) -> None:
    """Consume a topic continuously, dispatch records, and commit offsets.

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        topic: Topic to subscribe to.
        group_id: Consumer group identifier shared by this worker's instances.
        handler: Callback invoked with each decoded envelope and the producer
            bus used for replies.
        service_name: Optional liveness name. When provided, this consumer
            publishes a Kafka heartbeat every 30 seconds.

    This function runs until interrupted. Handler exceptions are logged and
    the corresponding record is still committed, so the worker does not retry
    that record automatically.

    Raises:
        RuntimeError: If Kafka returns a non-EOF consumer error.
        KafkaException: If a consumer cannot be created or subscribed.
    """
    from confluent_kafka import Consumer, KafkaError

    bus = KafkaBus(bootstrap_servers)
    consumer = Consumer(
        {
            **load_client_settings(bootstrap_servers).to_dict(),
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "max.partition.fetch.bytes": 80_000_000,
            "max.poll.interval.ms": 3_600_000,
        }
    )
    consumer.subscribe([topic])
    logger.info("Kafka consumer subscribed to %s", topic)
    heartbeat_reporter = None
    if service_name:
        from app.messaging.health import HeartbeatReporter

        heartbeat_reporter = HeartbeatReporter(bus, service_name)
        heartbeat_reporter.start()
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
        if heartbeat_reporter:
            heartbeat_reporter.stop()
        consumer.close()


def publish_reply(
    bus: KafkaBus,
    request: Envelope,
    payload: dict | None = None,
    error: str | None = None,
) -> None:
    """Publish a correlated response when the request has a reply topic.

    Args:
        bus: Kafka bus used to publish the reply envelope.
        request: Original request envelope carrying correlation metadata.
        payload: Optional success data to put in the response body.
        error: Optional failure description; sensitive values are redacted.
    """
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
    """Publish a redacted service failure to the notification topic.

    Args:
        bus: Kafka bus used to publish the notification.
        service: Name of the worker that failed.
        error: Exception whose type and sanitized message will be reported.
    """
    payload = {
        "service": service,
        "error_type": type(error).__name__,
        "error": sanitize_error(str(error)),
    }
    bus.publish(CORE_NOTIFICATIONS, Envelope.create("failure", payload))

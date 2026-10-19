"""Kafka client for acquiring permits from the centralized rate limiter."""

import logging
from threading import Event, Lock, Thread
from time import sleep
from uuid import uuid4

from app.contracts.models import Envelope
from app.messaging.config import load_client_settings
from app.messaging.exceptions import (
    RemoteServiceError,
    RetryableMessageError,
)
from app.messaging.kafka import KafkaBus
from app.messaging.topics import RATE_LIMIT_REQUESTS, RATE_LIMIT_RESPONSES

logger = logging.getLogger(__name__)


class RateLimitClient:
    """Request permits over Kafka while a background consumer receives replies.

    Each process owns one response consumer. This avoids creating and joining a
    Kafka consumer group for every external HTTP request.

    Args:
        bootstrap_servers: Kafka brokers used by this application process.
        service_name: Stable name included in this consumer's group ID.
        request_timeout_seconds: Deadline for each permit request/reply cycle.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        service_name: str,
        request_timeout_seconds: float = 30,
    ) -> None:
        from confluent_kafka import Consumer

        self.timeout = request_timeout_seconds
        self.bus = KafkaBus(bootstrap_servers)
        self._pending: dict[str, tuple[Event, list[Envelope]]] = {}
        self._pending_lock = Lock()
        self._ready = Event()
        self._consumer = Consumer(
            {
                **load_client_settings(bootstrap_servers).to_dict(),
                "group.id": f"rate-limit-client-{service_name}-{uuid4()}",
                "enable.auto.commit": False,
                "auto.offset.reset": "latest",
                "max.partition.fetch.bytes": 80_000_000,
            }
        )
        self._consumer.subscribe([RATE_LIMIT_RESPONSES])
        self._thread = Thread(
            target=self._listen,
            name=f"{service_name}-rate-limit-replies",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise RetryableMessageError(
                "Rate limiter response consumer did not receive a Kafka assignment"
            )

    def acquire(self, bucket: str) -> None:
        """Wait until the rate limiter grants a permit for ``bucket``.

        Args:
            bucket: Quota identifier configured in the rate-limiter service.

        Raises:
            RemoteServiceError: If the bucket is not configured.
            RetryableMessageError: If Kafka or the limiter backend is unavailable.
        """
        while True:
            correlation_id = str(uuid4())
            event = Event()
            result: list[Envelope] = []
            with self._pending_lock:
                self._pending[correlation_id] = (event, result)
            request = Envelope.create(
                "acquire_permit",
                {"bucket": bucket},
                correlation_id=correlation_id,
                reply_to=RATE_LIMIT_RESPONSES,
            )
            try:
                self.bus.publish(RATE_LIMIT_REQUESTS, request, key=bucket)
            except Exception as error:
                with self._pending_lock:
                    self._pending.pop(correlation_id, None)
                raise RetryableMessageError(
                    "Could not send permit request to the rate limiter"
                ) from error

            if not event.wait(self.timeout):
                with self._pending_lock:
                    self._pending.pop(correlation_id, None)
                raise RetryableMessageError(
                    f"Rate limiter did not answer permit request for {bucket}"
                )

            response = result[0]
            if response.error:
                if response.error.startswith("RATE_LIMIT_BACKEND_UNAVAILABLE"):
                    raise RetryableMessageError(
                        "Rate limiter Redis backend is unavailable"
                    )
                raise RemoteServiceError(response.error)

            if response.payload.get("granted") is True:
                return

            retry_after_ms = response.payload.get("retry_after_ms", 0)
            if (
                isinstance(retry_after_ms, bool)
                or not isinstance(retry_after_ms, int)
                or retry_after_ms < 0
            ):
                raise RemoteServiceError("Rate limiter returned an invalid delay")
            sleep(retry_after_ms / 1000)

    def _listen(self) -> None:
        """Route permit replies to their waiting caller threads."""
        from confluent_kafka import KafkaError

        try:
            while True:
                message = self._consumer.poll(1.0)
                if message is None:
                    if self._consumer.assignment():
                        self._ready.set()
                    continue
                if message.error():
                    if message.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    logger.error(
                        "Rate limiter response consumer error: %s", message.error()
                    )
                    continue

                response = Envelope.decode(message.value())
                if response.correlation_id:
                    with self._pending_lock:
                        pending = self._pending.pop(response.correlation_id, None)
                    if pending is not None:
                        event, result = pending
                        result.append(response)
                        event.set()
                self._consumer.commit(message=message, asynchronous=False)
                if self._consumer.assignment():
                    self._ready.set()
        except Exception:
            logger.exception("Rate limiter response listener stopped")
            self._ready.set()

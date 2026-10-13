"""Heartbeat publishing helpers for long-running Kafka services."""

from datetime import datetime, timezone
import logging
from threading import Event, Thread

from app.messaging.models import Envelope
from app.messaging.topics import HEALTH_HEARTBEATS

logger = logging.getLogger(__name__)


def publish_heartbeat(bus, service: str) -> None:
    """Publish a timestamped liveness heartbeat for one service.

    Args:
        bus: Kafka bus used to publish the heartbeat.
        service: Stable service name recognized by the health monitor.
    """
    sent_at = datetime.now(timezone.utc).timestamp()
    bus.publish(
        HEALTH_HEARTBEATS,
        Envelope.create("heartbeat", {"service": service, "sent_at": sent_at}),
        key=service,
    )


class HeartbeatReporter:
    """Publish liveness messages periodically on a daemon thread.

    Args:
        bus: Kafka bus shared with the worker process.
        service: Stable service name used in monitoring alerts.
        interval_seconds: Delay between heartbeats; the first is sent at start.
    """

    def __init__(self, bus, service: str, interval_seconds: float = 30) -> None:
        self.bus = bus
        self.service = service
        self.interval_seconds = interval_seconds
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start the background heartbeat loop once."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._publish_until_stopped,
            name=f"{self.service}-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 2) -> None:
        """Request shutdown and wait briefly for the reporting thread.

        Args:
            timeout_seconds: Maximum time to wait for the daemon thread.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout_seconds)

    def _publish_until_stopped(self) -> None:
        """Send an immediate heartbeat and continue until stopped."""
        while not self._stop_event.is_set():
            try:
                publish_heartbeat(self.bus, self.service)
            except Exception:
                logger.exception("Could not publish heartbeat for %s", self.service)
            if self._stop_event.wait(self.interval_seconds):
                return

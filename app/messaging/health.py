"""Heartbeat publishing helpers for long-running Kafka services."""

import logging
import time
from datetime import datetime, timezone
from threading import Event, Lock, Thread

from app.messaging.models import Envelope
from app.messaging.topics import HEALTH_HEARTBEATS

logger = logging.getLogger(__name__)


def publish_heartbeat(bus, service: str, busy_seconds: float = 0.0) -> None:
    """Publish a timestamped liveness heartbeat for one service.

    A heartbeat proves the process is alive, not that it is making progress, so
    it also reports how long the service has been busy with its current message.
    The health monitor uses that to spot a worker that is alive but stuck.

    Args:
        bus: Kafka bus used to publish the heartbeat.
        service: Stable service name recognized by the health monitor.
        busy_seconds: How long the service has been handling its current
            message; 0 while idle.
    """
    sent_at = datetime.now(timezone.utc).timestamp()
    payload = {
        "service": service,
        "sent_at": sent_at,
        "busy_seconds": round(max(0.0, busy_seconds), 1),
    }
    bus.publish(
        HEALTH_HEARTBEATS,
        Envelope.create("heartbeat", payload),
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
        self._busy_since: float | None = None
        self._busy_lock = Lock()

    def mark_busy(self) -> None:
        """Record that the worker started handling a message."""
        with self._busy_lock:
            self._busy_since = time.monotonic()

    def mark_idle(self) -> None:
        """Record that the worker finished handling its message."""
        with self._busy_lock:
            self._busy_since = None

    def busy_seconds(self) -> float:
        """Return how long the current message has been in progress.

        Returns:
            Seconds since ``mark_busy``, or 0 when the worker is idle.
        """
        with self._busy_lock:
            if self._busy_since is None:
                return 0.0
            return time.monotonic() - self._busy_since

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
                publish_heartbeat(self.bus, self.service, self.busy_seconds())
            except Exception:
                logger.exception("Could not publish heartbeat for %s", self.service)
            if self._stop_event.wait(self.interval_seconds):
                return

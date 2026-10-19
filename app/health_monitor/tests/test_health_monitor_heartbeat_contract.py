"""Contract tests: what workers publish is what the monitor understands."""

from app.health_monitor.monitor import HeartbeatTracker
from app.messaging.health import publish_heartbeat
from app.contracts.models import Envelope


class RecordingBus:
    def __init__(self):
        self.messages = []

    def publish(self, topic, message, key=None):
        self.messages.append(message)


def deliver(tracker, busy_seconds):
    """Publish a real heartbeat and feed its wire form to the tracker."""
    bus = RecordingBus()
    publish_heartbeat(bus, "core", busy_seconds=busy_seconds)
    received = Envelope.decode(bus.messages[0].encode())
    sent_at = received.payload["sent_at"]
    return tracker.record(received, now_monotonic=100.0, now_epoch=sent_at)


def make_tracker():
    return HeartbeatTracker(("core",), 120, 180, started_at=0, max_busy_seconds=600)


def test_a_published_heartbeat_is_accepted_by_the_monitor():
    tracker = make_tracker()

    assert deliver(tracker, busy_seconds=0.0) is True
    assert "core" in tracker.last_seen


def test_busy_time_survives_the_trip_through_the_wire_format():
    tracker = make_tracker()

    deliver(tracker, busy_seconds=734.26)

    assert tracker.busy_seconds["core"] == 734.3


def test_a_worker_blocked_past_the_limit_is_detected_end_to_end():
    tracker = make_tracker()
    deliver(tracker, busy_seconds=900.0)

    transitions = tracker.evaluate(now_monotonic=100.0)

    assert [(item.service, item.kind, item.available) for item in transitions] == [
        ("core", "stuck", False)
    ]

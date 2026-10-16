"""Tests for the heartbeat acceptance rules of the tracker."""

import pytest

from app.health_monitor.monitor import HeartbeatTracker
from app.messaging.models import Envelope

NOW_EPOCH = 1_700_000_000.0


def heartbeat(sent_at, service="core", command="heartbeat"):
    return Envelope.create(command, {"service": service, "sent_at": sent_at})


def make_tracker():
    return HeartbeatTracker(("core", "uploader"), 120, 180, started_at=0)


def record(tracker, message, now_monotonic=50.0):
    return tracker.record(message, now_monotonic=now_monotonic, now_epoch=NOW_EPOCH)


@pytest.mark.parametrize(
    "sent_at",
    [True, False, "1700000000", None, [1], float("inf"), float("-inf"), float("nan")],
)
def test_non_numeric_or_non_finite_timestamps_are_rejected(sent_at):
    tracker = make_tracker()

    assert record(tracker, heartbeat(sent_at)) is False
    assert tracker.last_seen == {}


def test_a_heartbeat_older_than_the_timeout_is_rejected():
    tracker = make_tracker()

    assert record(tracker, heartbeat(NOW_EPOCH - 121)) is False


def test_a_heartbeat_exactly_at_the_timeout_is_still_accepted():
    tracker = make_tracker()

    assert record(tracker, heartbeat(NOW_EPOCH - 120)) is True


def test_a_heartbeat_from_the_future_beyond_clock_skew_is_rejected():
    tracker = make_tracker()

    assert record(tracker, heartbeat(NOW_EPOCH + 6)) is False


def test_small_clock_skew_into_the_future_is_tolerated():
    tracker = make_tracker()

    assert record(tracker, heartbeat(NOW_EPOCH + 5)) is True


def test_a_replayed_or_older_heartbeat_does_not_move_last_seen_back():
    tracker = make_tracker()
    record(tracker, heartbeat(NOW_EPOCH - 10), now_monotonic=100.0)

    replayed = record(tracker, heartbeat(NOW_EPOCH - 30), now_monotonic=101.0)

    assert replayed is False
    assert tracker.last_seen["core"] == 90.0


def test_last_seen_accounts_for_the_age_of_the_heartbeat():
    tracker = make_tracker()

    record(tracker, heartbeat(NOW_EPOCH - 25), now_monotonic=200.0)

    assert tracker.last_seen["core"] == 175.0


def test_services_are_tracked_independently():
    tracker = make_tracker()

    record(tracker, heartbeat(NOW_EPOCH - 5, "core"))
    record(tracker, heartbeat(NOW_EPOCH - 5, "uploader"))

    assert set(tracker.last_seen) == {"core", "uploader"}


def test_other_commands_are_ignored():
    tracker = make_tracker()

    assert record(tracker, heartbeat(NOW_EPOCH, command="failure")) is False


def test_non_string_service_names_are_ignored():
    tracker = make_tracker()
    message = Envelope.create("heartbeat", {"service": 7, "sent_at": NOW_EPOCH})

    assert record(tracker, message) is False

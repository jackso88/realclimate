"""Tests for detecting a worker that is alive but stuck on one message."""

import pytest

from app.health_monitor.models import AVAILABILITY, STUCK, ServiceTransition
from app.health_monitor.monitor import (
    HeartbeatTracker,
    _format_duration,
    _transition_text,
)
from app.contracts.models import Envelope

NOW_EPOCH = 1_700_000_000.0


def make_tracker(services=("core",), **overrides):
    options = {"max_busy_seconds": 600, "busy_limits": None}
    options.update(overrides)
    return HeartbeatTracker(services, 120, 180, started_at=0, **options)


def beat(service="core", busy=None, age=0.0):
    payload = {"service": service, "sent_at": NOW_EPOCH - age}
    if busy is not None:
        payload["busy_seconds"] = busy
    return Envelope.create("heartbeat", payload)


def record(tracker, message, now_monotonic=1000.0):
    return tracker.record(message, now_monotonic=now_monotonic, now_epoch=NOW_EPOCH)


def stuck_transitions(transitions):
    return [item for item in transitions if item.kind == STUCK]


# ---------------------------------------------------------- reading busy time


def test_a_heartbeat_without_busy_time_counts_as_idle():
    tracker = make_tracker()

    record(tracker, beat())

    assert tracker.busy_seconds["core"] == 0.0


def test_the_reported_busy_time_is_stored():
    tracker = make_tracker()

    record(tracker, beat(busy=125.5))

    assert tracker.busy_seconds["core"] == 125.5


@pytest.mark.parametrize(
    "busy",
    [True, "300", None, -1, float("inf"), float("nan"), [5]],
)
def test_malformed_busy_time_is_ignored_without_rejecting_the_heartbeat(busy):
    tracker = make_tracker()
    message = beat()
    message.payload["busy_seconds"] = busy

    accepted = record(tracker, message)

    assert accepted is True
    assert tracker.busy_seconds["core"] == 0.0


def test_the_latest_heartbeat_replaces_the_previous_busy_time():
    tracker = make_tracker()
    record(tracker, beat(busy=500.0, age=20))

    record(tracker, beat(busy=0.0, age=0))

    assert tracker.busy_seconds["core"] == 0.0


# ------------------------------------------------------------ stuck detection


def test_a_worker_over_its_limit_is_reported_stuck_once():
    tracker = make_tracker()
    record(tracker, beat(busy=700.0))

    first = tracker.evaluate(now_monotonic=1000.0)
    second = tracker.evaluate(now_monotonic=1010.0)

    assert stuck_transitions(first) == [
        ServiceTransition(
            service="core",
            available=False,
            kind=STUCK,
            busy_seconds=700.0,
            limit_seconds=600,
        )
    ]
    assert stuck_transitions(second) == []


def test_a_worker_exactly_at_its_limit_is_not_stuck():
    tracker = make_tracker()
    record(tracker, beat(busy=600.0))

    assert stuck_transitions(tracker.evaluate(now_monotonic=1000.0)) == []


def test_a_busy_worker_within_its_limit_raises_no_alert():
    tracker = make_tracker()
    record(tracker, beat(busy=599.0))

    assert tracker.evaluate(now_monotonic=1000.0) == []


def test_a_worker_that_finishes_its_message_is_reported_recovered():
    tracker = make_tracker()
    record(tracker, beat(busy=700.0, age=40), now_monotonic=1000.0)
    tracker.evaluate(now_monotonic=1000.0)
    record(tracker, beat(busy=0.0, age=0), now_monotonic=1030.0)

    recovered = stuck_transitions(tracker.evaluate(now_monotonic=1030.0))

    assert [(item.service, item.available) for item in recovered] == [("core", True)]


def test_a_service_specific_limit_replaces_the_global_one():
    tracker = make_tracker(("core", "uploader"), busy_limits={"core": 100})
    record(tracker, beat("core", busy=150.0))
    record(tracker, beat("uploader", busy=150.0))

    transitions = stuck_transitions(tracker.evaluate(now_monotonic=1000.0))

    assert [item.service for item in transitions] == ["core"]
    assert transitions[0].limit_seconds == 100


def test_services_are_judged_independently():
    tracker = make_tracker(("core", "uploader"))
    record(tracker, beat("core", busy=900.0))
    record(tracker, beat("uploader", busy=10.0))

    transitions = stuck_transitions(tracker.evaluate(now_monotonic=1000.0))

    assert [item.service for item in transitions] == ["core"]


def test_an_outage_replaces_the_stuck_state_without_a_recovery_alert():
    tracker = make_tracker()
    record(tracker, beat(busy=700.0), now_monotonic=1000.0)
    tracker.evaluate(now_monotonic=1000.0)

    # No heartbeat for longer than the timeout: the service is simply down now.
    transitions = tracker.evaluate(now_monotonic=1000.0 + 121 + 200)

    assert [(item.kind, item.available) for item in transitions] == [
        (AVAILABILITY, False)
    ]
    assert tracker.stuck["core"] is False


def test_a_service_that_returns_after_an_outage_can_be_stuck_again():
    tracker = make_tracker()
    record(tracker, beat(busy=700.0, age=60), now_monotonic=1000.0)
    tracker.evaluate(now_monotonic=1000.0)
    tracker.evaluate(now_monotonic=1400.0)

    record(tracker, beat(busy=800.0, age=0), now_monotonic=1500.0)
    transitions = tracker.evaluate(now_monotonic=1500.0)

    assert [item.kind for item in transitions] == [AVAILABILITY, STUCK]


def test_a_service_that_never_reported_busy_time_is_never_stuck():
    tracker = make_tracker()
    record(tracker, beat())

    assert tracker.evaluate(now_monotonic=1000.0) == []


# -------------------------------------------------------------- alert wording


def test_stuck_alert_names_the_service_and_both_durations():
    transition = ServiceTransition(
        service="core",
        available=False,
        kind=STUCK,
        busy_seconds=6000.0,
        limit_seconds=5400,
    )

    text = _transition_text(transition, timeout_seconds=120)

    assert "«core»" in text
    assert "100 мин" in text
    assert "90 мин" in text
    assert text.startswith("⚠️")


def test_recovery_from_stuck_has_its_own_message():
    transition = ServiceTransition(service="core", available=True, kind=STUCK)

    text = _transition_text(transition, timeout_seconds=120)

    assert text == "✅ Сервис «core» завершил обработку сообщения."


def test_availability_messages_are_unchanged():
    down = _transition_text(
        ServiceTransition(service="core", available=False), timeout_seconds=120
    )
    up = _transition_text(
        ServiceTransition(service="core", available=True), timeout_seconds=120
    )

    assert (
        down == "🚨 Сервис «core» недоступен: heartbeat не поступал более 120 секунд."
    )
    assert up == "✅ Сервис «core» восстановил связь."


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0 с"), (45.9, "45 с"), (119, "119 с"), (120, "2 мин"), (5400, "90 мин")],
)
def test_durations_are_shown_in_seconds_when_short_and_minutes_otherwise(
    seconds, expected
):
    assert _format_duration(seconds) == expected

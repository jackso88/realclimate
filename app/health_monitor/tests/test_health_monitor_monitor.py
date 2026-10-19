"""Tests for health heartbeat tracking and alert delivery."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.health_monitor.models import HealthMonitorSettings, ServiceTransition
from app.health_monitor.monitor import (
    HeartbeatTracker,
    _check_broker,
    _send_broker_state,
    _send_transition,
    run_health_monitor,
)
from app.contracts.models import Envelope
from app.messaging.topics import HEALTH_HEARTBEATS


def make_heartbeat(service="core", sent_at=100.0):
    return Envelope.create("heartbeat", {"service": service, "sent_at": sent_at})


def test_tracker_records_only_fresh_known_heartbeats():
    tracker = HeartbeatTracker(("core",), 30, 10, started_at=0)

    assert tracker.record(make_heartbeat(), now_monotonic=20, now_epoch=100)
    assert not tracker.record(make_heartbeat(), now_monotonic=21, now_epoch=101)
    assert not tracker.record(
        Envelope.create("other", {"service": "core", "sent_at": 102}),
        now_monotonic=22,
        now_epoch=102,
    )
    assert not tracker.record(
        make_heartbeat("unknown", 103), now_monotonic=23, now_epoch=103
    )
    assert not tracker.record(
        make_heartbeat("core", 60), now_monotonic=24, now_epoch=100
    )
    assert not tracker.record(
        make_heartbeat("core", float("nan")), now_monotonic=24, now_epoch=100
    )
    assert tracker.last_seen == {"core": 20.0}


def test_tracker_waits_through_grace_then_reports_outage_and_recovery():
    tracker = HeartbeatTracker(("core",), 10, 5, started_at=0)

    assert tracker.evaluate(4) == []
    assert tracker.evaluate(5) == [ServiceTransition(service="core", available=False)]
    assert tracker.evaluate(6) == []
    assert tracker.record(make_heartbeat(sent_at=110), now_monotonic=7, now_epoch=110)
    assert tracker.evaluate(7) == [ServiceTransition(service="core", available=True)]
    assert tracker.evaluate(18) == [ServiceTransition(service="core", available=False)]


def test_tracker_does_not_alert_on_first_healthy_heartbeat():
    tracker = HeartbeatTracker(("core",), 10, 5, started_at=0)
    tracker.record(make_heartbeat(sent_at=100), now_monotonic=2, now_epoch=100)

    assert tracker.evaluate(2) == []


def test_check_broker_reports_connectivity_and_error():
    healthy = SimpleNamespace(list_topics=Mock(return_value=object()))
    broken = SimpleNamespace(list_topics=Mock(side_effect=RuntimeError("offline")))

    assert _check_broker(healthy) == (True, None)
    assert _check_broker(broken) == (False, "offline")


def test_send_transition_formats_outage_and_recovery():
    notifier = Mock()

    assert _send_transition(
        ServiceTransition(service="core", available=False), 60, notifier
    )
    assert "core" in notifier.call_args.args[0]
    assert "60 секунд" in notifier.call_args.args[0]
    assert _send_transition(
        ServiceTransition(service="core", available=True), 60, notifier
    )
    assert "восстановил связь" in notifier.call_args.args[0]


def test_send_helpers_retain_alert_when_notifier_fails():
    notifier = Mock(side_effect=RuntimeError("telegram down"))

    assert not _send_transition(
        ServiceTransition(service="core", available=False), 60, notifier
    )
    assert not _send_broker_state(False, "broker offline", notifier)
    assert _send_broker_state(True, None, Mock())


def test_run_health_monitor_subscribes_and_closes_consumer(monkeypatch):
    heartbeat = make_heartbeat(sent_at=100)

    class FakeMessage:
        def error(self):
            return None

        def value(self):
            return heartbeat.encode()

    class FakeConsumer:
        def __init__(self, config):
            self.config = config
            self.closed = False
            self.topics = None
            self.polls = iter([FakeMessage(), KeyboardInterrupt()])

        def subscribe(self, topics):
            self.topics = topics

        def poll(self, _timeout):
            result = next(self.polls)
            if isinstance(result, BaseException):
                raise result
            return result

        def close(self):
            self.closed = True

    consumer = FakeConsumer({})
    monkeypatch.setattr("app.health_monitor.monitor.Consumer", lambda config: consumer)
    monkeypatch.setattr(
        "app.health_monitor.monitor.AdminClient",
        lambda _config: SimpleNamespace(list_topics=Mock(return_value=object())),
    )
    monkeypatch.setattr(
        "app.health_monitor.monitor.load_client_settings",
        lambda _servers: SimpleNamespace(
            to_dict=lambda: {"bootstrap.servers": "broker"}
        ),
    )
    monkeypatch.setattr("app.health_monitor.monitor.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("app.health_monitor.monitor.time.time", lambda: 100.0)
    notifier = Mock()
    settings = HealthMonitorSettings(
        bootstrap_servers="broker",
        monitored_services=("core",),
        heartbeat_timeout_seconds=30,
        startup_grace_seconds=10,
        check_interval_seconds=1,
    )

    with pytest.raises(KeyboardInterrupt):
        run_health_monitor(settings, notifier)

    assert consumer.topics == [HEALTH_HEARTBEATS]
    assert consumer.closed
    notifier.assert_not_called()

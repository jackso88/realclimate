"""Scenario tests for the health monitor's polling loop.

Time and both Kafka clients are scripted, so every scenario is deterministic:
each scripted poll advances a fake clock and returns (or raises) one item.
"""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.health_monitor import monitor
from app.health_monitor.models import HealthMonitorSettings
from app.messaging.models import Envelope
from app.messaging.topics import HEALTH_HEARTBEATS

START = 1000.0
DOWN_TEXT = "🚨 Сервис «core» недоступен: heartbeat не поступал более 120 секунд."


class StopMonitor(BaseException):
    """Raised by the scripted consumer to leave the endless monitor loop.

    It derives from BaseException on purpose: the monitor swallows ordinary
    exceptions raised while polling, so an Exception subclass would never
    escape the loop.
    """


class FakeClock:
    """Stand-in for the ``time`` module with an explicitly advanced clock."""

    def __init__(self):
        self.now = START
        self.epoch_offset = 1_700_000_000.0 - START

    def monotonic(self):
        return self.now

    def time(self):
        return self.now + self.epoch_offset


class FakeKafkaError:
    def __init__(self, code=5, text="consumer failure"):
        self._code = code
        self._text = text

    def code(self):
        return self._code

    def str(self):
        return self._text


class FakeMessage:
    def __init__(self, value=b"", error=None):
        self._value = value
        self._error = error

    def value(self):
        return self._value

    def error(self):
        return self._error


class ScriptedConsumer:
    """Advance the clock, then return or raise the next scripted item."""

    def __init__(self, clock, script):
        self.clock = clock
        self.script = list(script)
        self.subscribed = None
        self.closed = False

    def subscribe(self, topics):
        self.subscribed = topics

    def poll(self, timeout):
        if not self.script:
            raise StopMonitor
        advance, item = self.script.pop(0)
        self.clock.now += advance
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item

    def close(self):
        self.closed = True


class FakeAdmin:
    """Return scripted broker outcomes; the last one repeats forever."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)

    def list_topics(self, timeout):
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome


def beat(clock, service="core"):
    """Build a script item that delivers a fresh heartbeat for ``service``."""

    def build():
        payload = {"service": service, "sent_at": clock.time()}
        return FakeMessage(Envelope.create("heartbeat", payload).encode())

    return build


def run_monitor(monkeypatch, clock, script, services=("core",), broker=(True,)):
    """Run the monitor against a script and return everything it touched."""
    consumer = ScriptedConsumer(clock, script)
    notifier = Mock()
    configs = []

    def make_consumer(config):
        configs.append(config)
        return consumer

    def load_settings(servers):
        return SimpleNamespace(to_dict=lambda: {"bootstrap.servers": servers})

    monkeypatch.setattr(monitor, "time", clock)
    monkeypatch.setattr(monitor, "Consumer", make_consumer)
    monkeypatch.setattr(monitor, "AdminClient", lambda config: FakeAdmin(broker))
    monkeypatch.setattr(monitor, "load_client_settings", load_settings)
    settings = HealthMonitorSettings(
        bootstrap_servers="kafka:9092",
        monitored_services=services,
        heartbeat_timeout_seconds=120,
        startup_grace_seconds=180,
        check_interval_seconds=30,
    )

    with pytest.raises(StopMonitor):
        monitor.run_health_monitor(settings, notifier=notifier)

    texts = [call.args[0] for call in notifier.call_args_list]
    return SimpleNamespace(
        consumer=consumer, configs=configs, notifier=notifier, texts=texts
    )


def test_consumer_listens_to_heartbeats_with_its_own_group(monkeypatch):
    run = run_monitor(monkeypatch, FakeClock(), [(0, None)])

    assert run.consumer.subscribed == [HEALTH_HEARTBEATS]
    assert run.configs[0]["group.id"] == "health-monitor"
    assert run.configs[0]["auto.offset.reset"] == "latest"
    assert run.consumer.closed


def test_unreachable_broker_at_startup_raises_an_alert_with_the_reason(monkeypatch):
    broker = (ConnectionError("connection refused"),)

    run = run_monitor(monkeypatch, FakeClock(), [(0, None)], broker=broker)

    assert run.texts == ["🚨 Kafka broker недоступен. Причина: connection refused"]


def test_broker_recovery_is_announced(monkeypatch):
    broker = (ConnectionError("connection refused"), True)

    run = run_monitor(monkeypatch, FakeClock(), [(0, None), (30, None)], broker=broker)

    assert run.texts == [
        "🚨 Kafka broker недоступен. Причина: connection refused",
        "✅ Kafka broker восстановил соединение.",
    ]


def test_a_healthy_start_sends_no_alerts(monkeypatch):
    clock = FakeClock()
    script = [(0, beat(clock)), (60, beat(clock)), (60, beat(clock))]

    run = run_monitor(monkeypatch, clock, script)

    assert run.texts == []


def test_silent_service_is_reported_down_and_then_recovered(monkeypatch):
    clock = FakeClock()
    script = [
        (0, beat(clock)),
        (60, None),
        (60, None),
        (60, None),
        (60, beat(clock)),
    ]

    run = run_monitor(monkeypatch, clock, script)

    assert run.texts == [DOWN_TEXT, "✅ Сервис «core» восстановил связь."]


def test_service_exactly_at_the_timeout_is_still_considered_alive(monkeypatch):
    clock = FakeClock()
    script = [(0, beat(clock)), (60, None), (60, None)]

    run = run_monitor(monkeypatch, clock, script)

    assert run.texts == []


def test_services_that_never_report_are_alerted_only_after_the_grace_period(
    monkeypatch,
):
    script = [(0, None), (90, None), (90, None), (30, None)]

    run = run_monitor(monkeypatch, FakeClock(), script, services=("core", "uploader"))

    assert len(run.texts) == 2
    assert "«core»" in run.texts[0]
    assert "«uploader»" in run.texts[1]


def test_no_alert_for_a_silent_service_inside_the_grace_period(monkeypatch):
    script = [(0, None), (90, None)]

    run = run_monitor(monkeypatch, FakeClock(), script)

    assert run.texts == []


def test_alerts_are_retried_after_the_interval_when_delivery_fails(monkeypatch):
    clock = FakeClock()
    notifier = Mock(side_effect=[RuntimeError("telegram down"), None])
    broker = (ConnectionError("down"),)
    consumer = ScriptedConsumer(clock, [(0, None), (10, None), (20, None)])
    monkeypatch.setattr(monitor, "time", clock)
    monkeypatch.setattr(monitor, "Consumer", lambda config: consumer)
    monkeypatch.setattr(monitor, "AdminClient", lambda config: FakeAdmin(broker))
    monkeypatch.setattr(
        monitor,
        "load_client_settings",
        lambda servers: SimpleNamespace(to_dict=lambda: {}),
    )
    settings = HealthMonitorSettings("kafka:9092", ("core",), 120, 180, 30)

    with pytest.raises(StopMonitor):
        monitor.run_health_monitor(settings, notifier=notifier)

    # Attempt 1 at t=1000 fails; t=1010 is too early; t=1030 retries.
    assert notifier.call_count == 2
    assert notifier.call_args_list[0] == notifier.call_args_list[1]


def test_grace_period_restarts_after_the_broker_reconnects(monkeypatch):
    clock = FakeClock()
    script = [(0, beat(clock)), (30, None), (30, None), (150, None)]
    broker = (True, ConnectionError("lost"), True)

    run = run_monitor(monkeypatch, clock, script, broker=broker)

    # At t=1210 the core heartbeat is 210 s old, but the grace window restarted
    # when the broker came back at t=1060, so there is no service alert yet.
    assert run.texts == [
        "🚨 Kafka broker недоступен. Причина: lost",
        "✅ Kafka broker восстановил соединение.",
    ]


def test_service_alert_follows_once_the_restarted_grace_period_ends(monkeypatch):
    clock = FakeClock()
    script = [(0, beat(clock)), (30, None), (30, None), (150, None), (40, None)]
    broker = (True, ConnectionError("lost"), True)

    run = run_monitor(monkeypatch, clock, script, broker=broker)

    assert run.texts[-1] == DOWN_TEXT
    assert len(run.texts) == 3


def test_service_state_is_not_evaluated_while_the_broker_is_down(monkeypatch):
    clock = FakeClock()
    script = [(0, beat(clock)), (30, None), (200, None)]
    broker = (True, ConnectionError("lost"))

    run = run_monitor(monkeypatch, clock, script, broker=broker)

    assert run.texts == ["🚨 Kafka broker недоступен. Причина: lost"]


def test_malformed_heartbeat_is_logged_and_ignored(monkeypatch, caplog):
    script = [(0, FakeMessage(b"not json at all")), (1, None)]

    with caplog.at_level(logging.ERROR, logger="app.health_monitor.monitor"):
        run = run_monitor(monkeypatch, FakeClock(), script)

    assert "Ignoring malformed health heartbeat" in caplog.text
    assert run.texts == []


def test_heartbeat_for_an_unmonitored_service_is_ignored(monkeypatch):
    clock = FakeClock()
    script = [(0, beat(clock, "stranger")), (200, None)]

    run = run_monitor(monkeypatch, clock, script)

    assert len(run.texts) == 1
    assert "«core»" in run.texts[0]


def test_consumer_poll_failures_are_logged_once_per_interval(monkeypatch, caplog):
    script = [(0, RuntimeError("boom")), (1, RuntimeError("boom")), (1, None)]

    with caplog.at_level(logging.ERROR, logger="app.health_monitor.monitor"):
        run_monitor(monkeypatch, FakeClock(), script)

    assert caplog.text.count("Health heartbeat consumer poll failed") == 1


def test_consumer_errors_are_warned_about_except_partition_eof(monkeypatch, caplog):
    eof = FakeMessage(error=FakeKafkaError(code=monitor.KafkaError._PARTITION_EOF))
    real = FakeMessage(error=FakeKafkaError(text="coordinator unavailable"))
    script = [(0, eof), (40, real), (1, real)]

    with caplog.at_level(logging.WARNING, logger="app.health_monitor.monitor"):
        run_monitor(monkeypatch, FakeClock(), script)

    assert caplog.text.count("Heartbeat consumer error: coordinator unavailable") == 1
    assert "-191" not in caplog.text

"""Tests for heartbeat publishing helpers."""

import logging
import time
from types import SimpleNamespace

from app.messaging import health
from app.messaging.health import HeartbeatReporter, publish_heartbeat
from app.messaging.topics import HEALTH_HEARTBEATS


class RecordingBus:
    """Collect published messages and optionally run a hook after each one."""

    def __init__(self, on_publish=None):
        self.published = []
        self.on_publish = on_publish

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))
        if self.on_publish:
            self.on_publish(len(self.published))


class FakeThread:
    """Record how the reporter configures and drives its background thread."""

    def __init__(self, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.alive = False
        self.joined_with = None

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.joined_with = timeout


def install_fake_threads(monkeypatch):
    """Replace the module's Thread class and return the list of created threads."""
    threads = []

    def make_thread(**kwargs):
        thread = FakeThread(**kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(health, "Thread", make_thread)
    return threads


def test_publish_heartbeat_sends_service_name_and_timestamp():
    bus = RecordingBus()
    before = time.time()

    publish_heartbeat(bus, "core")

    after = time.time()
    topic, message, key = bus.published[0]
    assert topic == HEALTH_HEARTBEATS
    assert key == "core"
    assert message.command == "heartbeat"
    assert message.payload["service"] == "core"
    assert before - 1 <= message.payload["sent_at"] <= after + 1


def test_reporter_publishes_until_stopped():
    holder = {}

    def stop_after_three(count):
        if count == 3:
            holder["reporter"]._stop_event.set()

    bus = RecordingBus(on_publish=stop_after_three)
    holder["reporter"] = HeartbeatReporter(bus, "uploader", interval_seconds=0)

    holder["reporter"]._publish_until_stopped()

    assert len(bus.published) == 3
    assert {key for _, _, key in bus.published} == {"uploader"}


def test_reporter_keeps_running_after_a_publish_failure(caplog):
    holder = {}
    calls = []

    def publish(topic, message, key=None):
        calls.append(key)
        if len(calls) == 1:
            raise RuntimeError("broker down")
        holder["reporter"]._stop_event.set()

    holder["reporter"] = HeartbeatReporter(
        SimpleNamespace(publish=publish), "core", interval_seconds=0
    )

    with caplog.at_level(logging.ERROR, logger="app.messaging.health"):
        holder["reporter"]._publish_until_stopped()

    assert len(calls) == 2
    assert "Could not publish heartbeat for core" in caplog.text


def test_start_launches_a_named_daemon_thread(monkeypatch):
    threads = install_fake_threads(monkeypatch)
    reporter = HeartbeatReporter(RecordingBus(), "core")

    reporter.start()

    assert len(threads) == 1
    assert threads[0].name == "core-heartbeat"
    assert threads[0].daemon is True
    assert threads[0].target == reporter._publish_until_stopped
    assert threads[0].alive is True


def test_start_is_idempotent_while_the_thread_is_alive(monkeypatch):
    threads = install_fake_threads(monkeypatch)
    reporter = HeartbeatReporter(RecordingBus(), "core")

    reporter.start()
    reporter.start()

    assert len(threads) == 1


def test_start_after_the_thread_died_creates_a_fresh_thread(monkeypatch):
    threads = install_fake_threads(monkeypatch)
    reporter = HeartbeatReporter(RecordingBus(), "core")
    reporter.start()
    threads[0].alive = False
    reporter._stop_event.set()

    reporter.start()

    assert len(threads) == 2
    assert not reporter._stop_event.is_set()


def test_stop_signals_the_loop_and_joins_with_the_timeout(monkeypatch):
    threads = install_fake_threads(monkeypatch)
    reporter = HeartbeatReporter(RecordingBus(), "core")
    reporter.start()

    reporter.stop(timeout_seconds=5)

    assert reporter._stop_event.is_set()
    assert threads[0].joined_with == 5


def test_stop_without_start_only_sets_the_event():
    reporter = HeartbeatReporter(RecordingBus(), "core")

    reporter.stop()

    assert reporter._stop_event.is_set()

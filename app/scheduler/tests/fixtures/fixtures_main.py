"""Fixtures for the scheduler entrypoint tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def scheduler_daemon(monkeypatch):
    """Replace every collaborator of ``main`` and record the call order."""
    from app.scheduler import main as scheduler_main

    events = []
    scheduler = Mock()
    scheduler.start.side_effect = lambda: events.append("scheduler.start")
    heartbeat = Mock()
    heartbeat.start.side_effect = lambda: events.append("heartbeat.start")
    heartbeat.stop.side_effect = lambda: events.append("heartbeat.stop")
    parts = SimpleNamespace(
        events=events,
        scheduler=scheduler,
        heartbeat=heartbeat,
        scheduler_cls=Mock(return_value=scheduler),
        trigger_cls=Mock(return_value="cron-trigger"),
        bus_cls=Mock(return_value="bus"),
        heartbeat_cls=Mock(return_value=heartbeat),
        logging=Mock(),
    )
    monkeypatch.setattr(scheduler_main, "configure_logging", parts.logging)
    monkeypatch.setattr(scheduler_main, "BlockingScheduler", parts.scheduler_cls)
    monkeypatch.setattr(scheduler_main, "CronTrigger", parts.trigger_cls)
    monkeypatch.setattr(scheduler_main, "KafkaBus", parts.bus_cls)
    monkeypatch.setattr(scheduler_main, "HeartbeatReporter", parts.heartbeat_cls)
    monkeypatch.delenv("SCHEDULE_TIMEZONE", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    return parts

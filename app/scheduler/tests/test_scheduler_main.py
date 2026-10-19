"""Tests for the weekday hourly scheduler daemon."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.scheduler import main as scheduler_main
from app.scheduler.producer import publish_reference_sync


@pytest.fixture
def daemon(monkeypatch):
    """Replace every collaborator of ``main`` and record the call order."""
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


def test_main_configures_logging(daemon):
    scheduler_main.main()

    daemon.logging.assert_called_once_with()


def test_schedule_is_every_weekday_hour_from_nine_to_seventeen(daemon):
    scheduler_main.main()

    daemon.trigger_cls.assert_called_once_with(
        day_of_week="mon-fri",
        hour="9-17",
        minute=0,
        timezone="Europe/Minsk",
    )


def test_registers_a_single_coalescing_job(daemon):
    scheduler_main.main()

    daemon.scheduler.add_job.assert_called_once()
    args, kwargs = daemon.scheduler.add_job.call_args
    assert args[0].func is publish_reference_sync
    assert args[0].keywords["settings"].timezone == "Europe/Minsk"
    assert args[1] == "cron-trigger"
    assert kwargs == {
        "id": "hourly-catalogue-run",
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 300,
    }


def test_timezone_defaults_to_minsk(daemon):
    scheduler_main.main()

    daemon.scheduler_cls.assert_called_once_with(timezone="Europe/Minsk")


def test_timezone_can_be_overridden_from_the_environment(daemon, monkeypatch):
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "UTC")

    scheduler_main.main()

    daemon.scheduler_cls.assert_called_once_with(timezone="UTC")
    assert daemon.trigger_cls.call_args.kwargs["timezone"] == "UTC"


def test_heartbeat_runs_for_the_whole_life_of_the_scheduler(daemon):
    scheduler_main.main()

    assert daemon.events == ["heartbeat.start", "scheduler.start", "heartbeat.stop"]
    daemon.heartbeat_cls.assert_called_once_with("bus", "scheduler")


def test_heartbeat_is_stopped_even_when_the_scheduler_crashes(daemon):
    daemon.scheduler.start.side_effect = RuntimeError("scheduler crashed")

    with pytest.raises(RuntimeError, match="scheduler crashed"):
        scheduler_main.main()

    assert daemon.heartbeat.stop.call_count == 1


def test_bus_uses_the_configured_bootstrap_servers(daemon, monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

    scheduler_main.main()

    daemon.bus_cls.assert_called_once_with("kafka:9092")


def test_bus_defaults_to_localhost(daemon):
    scheduler_main.main()

    daemon.bus_cls.assert_called_once_with("localhost:9092")

"""Tests for the weekday hourly scheduler scheduler_daemon."""

import pytest

from app.scheduler import main as scheduler_main
from app.scheduler.producer import publish_reference_sync


def test_main_configures_logging(scheduler_daemon):
    scheduler_main.main()

    scheduler_daemon.logging.assert_called_once_with()


def test_schedule_is_every_weekday_hour_from_nine_to_seventeen(scheduler_daemon):
    scheduler_main.main()

    scheduler_daemon.trigger_cls.assert_called_once_with(
        day_of_week="mon-fri",
        hour="9-17",
        minute=0,
        timezone="Europe/Minsk",
    )


def test_registers_a_single_coalescing_job(scheduler_daemon):
    scheduler_main.main()

    scheduler_daemon.scheduler.add_job.assert_called_once()
    args, kwargs = scheduler_daemon.scheduler.add_job.call_args
    assert args[0].func is publish_reference_sync
    assert args[0].keywords["settings"].timezone == "Europe/Minsk"
    assert args[1] == "cron-trigger"
    assert kwargs == {
        "id": "hourly-catalogue-run",
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 300,
    }


def test_timezone_defaults_to_minsk(scheduler_daemon):
    scheduler_main.main()

    scheduler_daemon.scheduler_cls.assert_called_once_with(timezone="Europe/Minsk")


def test_timezone_can_be_overridden_from_the_environment(scheduler_daemon, monkeypatch):
    monkeypatch.setenv("SCHEDULE_TIMEZONE", "UTC")

    scheduler_main.main()

    scheduler_daemon.scheduler_cls.assert_called_once_with(timezone="UTC")
    assert scheduler_daemon.trigger_cls.call_args.kwargs["timezone"] == "UTC"


def test_heartbeat_runs_for_the_whole_life_of_the_scheduler(scheduler_daemon):
    scheduler_main.main()

    assert scheduler_daemon.events == [
        "heartbeat.start",
        "scheduler.start",
        "heartbeat.stop",
    ]
    scheduler_daemon.heartbeat_cls.assert_called_once_with("bus", "scheduler")


def test_heartbeat_is_stopped_even_when_the_scheduler_crashes(scheduler_daemon):
    scheduler_daemon.scheduler.start.side_effect = RuntimeError("scheduler crashed")

    with pytest.raises(RuntimeError, match="scheduler crashed"):
        scheduler_main.main()

    assert scheduler_daemon.heartbeat.stop.call_count == 1


def test_bus_uses_the_configured_bootstrap_servers(scheduler_daemon, monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

    scheduler_main.main()

    scheduler_daemon.bus_cls.assert_called_once_with("kafka:9092")


def test_bus_defaults_to_localhost(scheduler_daemon):
    scheduler_main.main()

    scheduler_daemon.bus_cls.assert_called_once_with("localhost:9092")

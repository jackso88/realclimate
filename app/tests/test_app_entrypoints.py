"""Smoke tests for the modules that compose runs as ``python -m <module>``.

Each module is executed the way the container does it (as ``__main__``), with
the long-running parts replaced by mocks, to prove that the entry point is
wired to the right topic, consumer group and heartbeat name.
"""

import logging
import runpy
import warnings
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.messaging.topics import (
    ADMIN_AUTH_REQUESTS,
    CORE_NOTIFICATIONS,
    CORE_PROCESS_REQUESTS,
    CURRENT_DOWNLOAD_REQUESTS,
    ORCHESTRATOR_RUNS,
    REFERENCE_DOWNLOAD_REQUESTS,
    UPLOADER_REQUESTS,
)

CONSUMER_ENTRYPOINTS = [
    (
        "app.admin_auth.consumer",
        ADMIN_AUTH_REQUESTS,
        "admin-auth-service",
        "admin_auth",
    ),
    (
        "app.downloader.current.consumer",
        CURRENT_DOWNLOAD_REQUESTS,
        "current-downloader-service",
        "downloader_current",
    ),
    (
        "app.downloader.reference.consumer",
        REFERENCE_DOWNLOAD_REQUESTS,
        "reference-downloader-service",
        "downloader_reference",
    ),
    ("app.core.consumer", CORE_PROCESS_REQUESTS, "core-service", "core"),
    (
        "app.orchestrator.consumer",
        ORCHESTRATOR_RUNS,
        "orchestrator-service",
        "orchestrator",
    ),
    ("app.uploader.consumer", UPLOADER_REQUESTS, "uploader-service", "uploader"),
    (
        "app.notifications.consumer",
        CORE_NOTIFICATIONS,
        "telegram-notifications",
        "notifications",
    ),
]


def run_as_main(module_name):
    """Execute a module like ``python -m`` would, without reload warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module(module_name, run_name="__main__")


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch):
    monkeypatch.setattr(logging, "basicConfig", Mock())
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)


@pytest.mark.parametrize(
    ("module_name", "topic", "group", "service"), CONSUMER_ENTRYPOINTS
)
def test_consumer_entrypoints_listen_to_their_own_topic(
    monkeypatch, module_name, topic, group, service
):
    run_consumer = Mock()
    monkeypatch.setattr("app.messaging.kafka.run_consumer", run_consumer)

    run_as_main(module_name)

    run_consumer.assert_called_once()
    args = run_consumer.call_args
    assert args.args[0] == "localhost:9092"
    assert args.args[1] == topic
    assert args.args[2] == group
    assert args.kwargs["service_name"] == service


def test_scheduler_entrypoint_starts_the_blocking_scheduler(monkeypatch):
    scheduler = Mock()
    monkeypatch.setattr(
        "apscheduler.schedulers.blocking.BlockingScheduler",
        Mock(return_value=scheduler),
    )
    monkeypatch.setattr("apscheduler.triggers.cron.CronTrigger", Mock())
    monkeypatch.setattr("app.messaging.kafka.KafkaBus", Mock())
    monkeypatch.setattr("app.messaging.health.HeartbeatReporter", Mock())

    run_as_main("app.scheduler.main")

    scheduler.add_job.assert_called_once()
    scheduler.start.assert_called_once_with()


def test_health_monitor_entrypoint_runs_the_monitor(monkeypatch):
    run = Mock()
    monkeypatch.setattr("app.health_monitor.monitor.run_health_monitor", run)

    run_as_main("app.health_monitor.main")

    run.assert_called_once()
    assert run.call_args.args[0].bootstrap_servers == "localhost:9092"


def test_top_level_app_module_delegates_to_the_scheduler(monkeypatch):
    scheduler_main = Mock()
    monkeypatch.setattr("app.scheduler.main.main", scheduler_main)

    run_as_main("app.main")

    scheduler_main.assert_called_once_with()


def test_reference_auth_cli_entrypoint_authorizes_google_once(monkeypatch):
    settings = SimpleNamespace(credentials_file="c.json", token_file="t.json")
    get_credentials = Mock()
    monkeypatch.setattr(
        "app.downloader.reference.config.load_settings", lambda: settings
    )
    monkeypatch.setattr(
        "app.downloader.reference.google_oauth.get_credentials", get_credentials
    )

    run_as_main("app.downloader.reference.auth_cli")

    get_credentials.assert_called_once()
    assert get_credentials.call_args.args[:2] == ("c.json", "t.json")

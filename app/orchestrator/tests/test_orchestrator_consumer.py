"""Tests for the orchestrator Kafka handler and its worker wiring."""

import logging
from unittest.mock import Mock

import pytest

from app.messaging.models import Envelope
from app.messaging.topics import ORCHESTRATOR_RUNS
from app.orchestrator import consumer
from app.orchestrator.models import OrchestratorSettings


@pytest.fixture
def collaborators(monkeypatch):
    """Replace the workflow and the reply helpers with mocks."""
    parts = type("Parts", (), {})()
    parts.run = Mock(return_value={"status": "processed", "uploaded": True})
    parts.reply = Mock()
    parts.failure = Mock()
    monkeypatch.setattr(consumer, "load_settings", lambda: "settings")
    monkeypatch.setattr(consumer, "run_workflow", parts.run)
    monkeypatch.setattr(consumer, "publish_reply", parts.reply)
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    return parts


def make_request():
    return Envelope.create(
        "run_workflow",
        {"source": "scheduler"},
        correlation_id="run-1",
        reply_to="orchestrator.run.responses",
    )


def test_successful_run_is_returned_to_the_requester(collaborators):
    bus = object()
    request = make_request()

    consumer.handle_run(request, bus)

    collaborators.run.assert_called_once_with(bus, "settings")
    collaborators.reply.assert_called_once_with(
        bus, request, {"status": "processed", "uploaded": True}
    )
    collaborators.failure.assert_not_called()


def test_successful_run_logs_the_outcome(collaborators, caplog):
    with caplog.at_level(logging.INFO, logger="app.orchestrator.consumer"):
        consumer.handle_run(make_request(), object())

    assert "status=processed" in caplog.text
    assert "uploaded=True" in caplog.text


def test_failed_run_notifies_the_admin_and_replies_with_the_error(collaborators):
    bus = object()
    request = make_request()
    error = RuntimeError("core exploded")
    collaborators.run.side_effect = error

    consumer.handle_run(request, bus)

    collaborators.failure.assert_called_once_with(bus, "orchestrator", error)
    collaborators.reply.assert_called_once_with(bus, request, error="core exploded")


def test_failed_settings_load_is_reported_like_any_other_failure(
    collaborators, monkeypatch
):
    def broken_settings():
        raise ValueError("DOWNLOAD_TIMEOUT_SECONDS must be a positive integer")

    monkeypatch.setattr(consumer, "load_settings", broken_settings)

    consumer.handle_run(make_request(), object())

    collaborators.run.assert_not_called()
    assert "DOWNLOAD_TIMEOUT_SECONDS" in collaborators.reply.call_args.kwargs["error"]


def test_main_runs_the_orchestrator_worker(monkeypatch):
    run_consumer = Mock()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", lambda: OrchestratorSettings())
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    consumer.main()

    run_consumer.assert_called_once_with(
        "localhost:9092",
        ORCHESTRATOR_RUNS,
        "orchestrator-service",
        consumer.handle_run,
        service_name="orchestrator",
        max_poll_interval_ms=5_100_000,
    )


def test_main_sizes_the_poll_interval_from_the_configured_timeouts(monkeypatch):
    run_consumer = Mock()
    settings = OrchestratorSettings(
        request_timeout_seconds=1800, uploader_timeout_seconds=3600
    )
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)

    consumer.main()

    expected_seconds = 3 * 1800 + 3600 + consumer.POLL_INTERVAL_MARGIN_SECONDS
    interval = run_consumer.call_args.kwargs["max_poll_interval_ms"]
    assert interval == expected_seconds * 1000


def test_main_stops_at_startup_when_a_timeout_is_invalid(monkeypatch):
    run_consumer = Mock()

    def broken_settings():
        raise ValueError("IMPORT_TIMEOUT_SECONDS must be a positive integer")

    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", broken_settings)

    with pytest.raises(ValueError, match="IMPORT_TIMEOUT_SECONDS"):
        consumer.main()

    run_consumer.assert_not_called()


def test_poll_interval_covers_the_worst_case_run_plus_a_margin():
    settings = OrchestratorSettings()

    interval_seconds = consumer.max_poll_interval_ms(settings) / 1000

    assert interval_seconds == settings.worst_case_run_seconds + 600
    assert interval_seconds > settings.worst_case_run_seconds


def test_poll_interval_never_drops_below_the_kafka_default():
    settings = OrchestratorSettings(
        request_timeout_seconds=10, uploader_timeout_seconds=10
    )

    assert consumer.max_poll_interval_ms(settings) == 3_600_000


def test_a_default_run_would_have_outlasted_the_old_one_hour_limit():
    # Regression guard for the reason this setting exists: with the default
    # timeouts a worst-case run takes longer than Kafka's default interval.
    assert OrchestratorSettings().worst_case_run_seconds > 3600

"""Tests for the orchestrator Kafka handler and its worker wiring."""

import logging
from unittest.mock import Mock

import pytest

from app.messaging.models import Envelope
from app.messaging.topics import ORCHESTRATOR_RUNS
from app.orchestrator import consumer


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
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    consumer.main()

    run_consumer.assert_called_once_with(
        "localhost:9092",
        ORCHESTRATOR_RUNS,
        "orchestrator-service",
        consumer.handle_run,
        service_name="orchestrator",
    )

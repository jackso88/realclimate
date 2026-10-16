"""Tests for the scheduled workflow request."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.messaging.exceptions import RemoteServiceError, RequestTimeoutError
from app.messaging.topics import ORCHESTRATOR_RUN_RESPONSES, ORCHESTRATOR_RUNS
from app.scheduler import producer


@pytest.fixture
def bus(monkeypatch):
    """Replace KafkaBus with a mock whose request returns a processed result."""
    mock_bus = Mock()
    mock_bus.request.return_value = SimpleNamespace(
        payload={"status": "processed", "changes_count": 3, "uploaded": True}
    )
    monkeypatch.setattr(producer, "KafkaBus", Mock(return_value=mock_bus))
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_RUN_TIMEOUT_SECONDS", raising=False)
    return mock_bus


def test_requests_a_workflow_run_from_the_orchestrator(bus):
    producer.publish_workflow_run()

    bus.request.assert_called_once_with(
        ORCHESTRATOR_RUNS,
        ORCHESTRATOR_RUN_RESPONSES,
        "run_workflow",
        {"source": "scheduler"},
        timeout=5400.0,
        response_group="scheduler-orchestrator-rpc",
    )


def test_timeout_comes_from_the_environment(bus, monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR_RUN_TIMEOUT_SECONDS", "120")

    producer.publish_workflow_run()

    assert bus.request.call_args.kwargs["timeout"] == 120.0


def test_bus_uses_the_configured_bootstrap_servers(bus, monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

    producer.publish_workflow_run()

    producer.KafkaBus.assert_called_once_with("kafka:9092")


def test_logs_a_summary_of_the_workflow_result(bus, caplog):
    with caplog.at_level(logging.INFO, logger="app.scheduler.producer"):
        producer.publish_workflow_run()

    assert "status=processed" in caplog.text
    assert "changes=3" in caplog.text
    assert "uploaded=True" in caplog.text


def test_an_empty_reply_payload_is_reported_as_unknown(bus, caplog):
    bus.request.return_value = SimpleNamespace(payload={})

    with caplog.at_level(logging.INFO, logger="app.scheduler.producer"):
        producer.publish_workflow_run()

    assert "status=unknown" in caplog.text


@pytest.mark.parametrize(
    "error",
    [RequestTimeoutError("slow"), RemoteServiceError("remote failure")],
)
def test_failures_propagate_so_the_scheduler_logs_them(bus, error):
    bus.request.side_effect = error

    with pytest.raises(type(error)):
        producer.publish_workflow_run()

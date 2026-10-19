"""Tests for publishing scheduled reference synchronization events."""

import logging
from unittest.mock import Mock

from app.contracts.models import Envelope
from app.messaging.topics import REFERENCE_SYNC_REQUESTS
from app.scheduler import producer


def test_publishes_reference_sync_event_with_a_correlation_id(monkeypatch):
    bus = Mock()
    monkeypatch.setattr(producer, "KafkaBus", Mock(return_value=bus))
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.delenv("SCHEDULE_TIMEZONE", raising=False)

    correlation_id = producer.publish_reference_sync()

    producer.KafkaBus.assert_called_once_with("kafka:9092")
    bus.publish.assert_called_once()
    topic, event = bus.publish.call_args.args
    assert topic == REFERENCE_SYNC_REQUESTS
    assert event.command == "sync_reference"
    assert event.payload == {"source": "scheduler"}
    assert event.correlation_id == correlation_id
    assert bus.publish.call_args.kwargs == {"key": correlation_id}


def test_uses_settings_loaded_at_scheduler_startup(monkeypatch):
    bus = Mock()
    monkeypatch.setattr(producer, "KafkaBus", Mock(return_value=bus))
    settings = producer.SchedulerSettings.model_validate(
        {"KAFKA_BOOTSTRAP_SERVERS": "broker:9092"}
    )

    producer.publish_reference_sync(settings)

    producer.KafkaBus.assert_called_once_with("broker:9092")


def test_logs_the_pipeline_correlation_id(monkeypatch, caplog):
    bus = Mock()
    monkeypatch.setattr(producer, "KafkaBus", Mock(return_value=bus))
    with caplog.at_level(logging.INFO, logger="app.scheduler.producer"):
        correlation_id = producer.publish_reference_sync()

    assert correlation_id in caplog.text


def test_published_sync_request_is_a_valid_contract(monkeypatch):
    bus = Mock()
    monkeypatch.setattr(producer, "KafkaBus", Mock(return_value=bus))

    producer.publish_reference_sync()

    event = bus.publish.call_args.args[1]
    assert Envelope.decode(event.encode()) == event

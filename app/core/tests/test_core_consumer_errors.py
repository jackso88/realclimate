"""Tests for core event validation, retry propagation, and worker wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.contracts.models import Envelope
from app.core import consumer
from app.core.models import CoreSettings
from app.messaging.exceptions import RetryableMessageError
from app.messaging.payloads import encode_bytes
from app.messaging.topics import CURRENT_DOWNLOADS, REFERENCE_DOWNLOADS


class FakePendingInputs:
    def __init__(self):
        self.parts = {}
        self.released = []

    def is_completed(self, correlation_id):
        return False

    def save_reference(self, correlation_id, content, sha256, claim_token):
        self.parts[correlation_id] = {"reference": content, "sha256": sha256}
        return False

    def save_current(self, correlation_id, content, claim_token):
        return False

    def release(self, correlation_id, token):
        self.released.append((correlation_id, token))


class FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))


def test_unsupported_commands_are_reported_and_propagated(monkeypatch):
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_failure", failure)
    message = Envelope.create("unsupported", {}, correlation_id="run-x")

    with pytest.raises(ValueError, match="Unsupported core command"):
        consumer.handle_process(message, FakeBus(), CoreSettings(), FakePendingInputs())

    assert failure.call_args.args[2].args == ("Unsupported core command: unsupported",)


def test_missing_correlation_id_is_rejected(monkeypatch):
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_failure", failure)
    message = Envelope.create(
        "reference_downloaded",
        {"reference_csv_gzip_base64": encode_bytes(b"ref"), "reference_sha256": "x"},
    )

    with pytest.raises(ValueError, match="missing correlation_id"):
        consumer.handle_process(message, FakeBus(), CoreSettings(), FakePendingInputs())

    failure.assert_called_once()


def test_redis_failure_is_reported_as_retryable_for_kafka(monkeypatch):
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_failure", failure)
    pending = FakePendingInputs()
    pending.save_reference = Mock(side_effect=OSError("redis unavailable"))
    message = Envelope.create(
        "reference_downloaded",
        {"reference_csv_gzip_base64": encode_bytes(b"ref"), "reference_sha256": "x"},
        correlation_id="run-redis-error",
    )

    with pytest.raises(RetryableMessageError, match="Redis failed"):
        consumer.handle_process(message, FakeBus(), CoreSettings(), pending)

    failure.assert_called_once()


def test_core_main_creates_redis_store_and_subscribes_to_both_sources(monkeypatch):
    run_consumer = Mock()
    store = SimpleNamespace(client=SimpleNamespace(close=Mock()))
    settings = CoreSettings()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "create_pending_inputs_store", lambda _: store)

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == (
        settings.bootstrap_servers,
        [REFERENCE_DOWNLOADS, CURRENT_DOWNLOADS],
        "core-service",
    )
    assert args[3].func is consumer.handle_process
    assert args[3].keywords == {"settings": settings, "pending_inputs": store}
    assert kwargs == {"service_name": "core"}
    store.client.close.assert_called_once_with()

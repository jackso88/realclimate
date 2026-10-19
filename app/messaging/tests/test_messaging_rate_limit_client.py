"""Tests for Kafka request/reply behavior in the rate-limit client."""

import sys
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from app.contracts.models import Envelope
from app.messaging import rate_limit_client as module
from app.messaging.exceptions import RemoteServiceError, RetryableMessageError


class FakeConsumer:
    """Scripted Kafka consumer for the client's reply listener."""

    def __init__(self, records=(), assigned=True):
        self.records = list(records)
        self.assigned = assigned
        self.subscriptions = []
        self.commits = []

    def subscribe(self, topics):
        self.subscriptions.append(topics)

    def poll(self, _timeout):
        if not self.records:
            return None
        item = self.records.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def assignment(self):
        return [object()] if self.assigned else []

    def commit(self, **kwargs):
        self.commits.append(kwargs)


class FakeMessage:
    def __init__(self, envelope=None, error=None):
        self._envelope = envelope
        self._error = error

    def error(self):
        return self._error

    def value(self):
        return self._envelope.encode()


class InlineThread:
    """Make listener readiness deterministic without starting a real thread."""

    def __init__(self, *, target, **_kwargs):
        self.target = target

    def start(self):
        # The listener is tested independently; initialization only waits for assignment.
        return None


def make_client(bus=None, timeout=0.01):
    client = object.__new__(module.RateLimitClient)
    client.timeout = timeout
    client.bus = bus or Mock()
    client._pending = {}
    client._pending_lock = threading.Lock()
    return client


def respond_to_request(client, payload=None, error=None):
    """Return a fake producer callback which completes the pending RPC."""

    def publish(_topic, request, key=None):
        with client._pending_lock:
            event, result = client._pending.pop(request.correlation_id)
        result.append(
            Envelope.create(
                "response",
                payload or {},
                correlation_id=request.correlation_id,
                error=error,
            )
        )
        event.set()

    return publish


def test_constructor_subscribes_and_waits_for_kafka_assignment(monkeypatch):
    fake_consumer = FakeConsumer()
    fake_kafka = ModuleType("confluent_kafka")
    fake_kafka.Consumer = lambda _config: fake_consumer
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_kafka)
    monkeypatch.setattr(
        module,
        "load_client_settings",
        lambda _servers: SimpleNamespace(to_dict=lambda: {}),
    )
    bus = Mock()
    monkeypatch.setattr(module, "KafkaBus", lambda _servers: bus)
    monkeypatch.setattr(module, "Thread", InlineThread)
    monkeypatch.setattr(module.Event, "wait", lambda _self, timeout=None: True)

    client = module.RateLimitClient("broker:9093", "worker")

    assert client.bus is bus
    assert fake_consumer.subscriptions == [[module.RATE_LIMIT_RESPONSES]]


def test_constructor_raises_if_consumer_never_gets_assignment(monkeypatch):
    fake_consumer = FakeConsumer()
    fake_kafka = ModuleType("confluent_kafka")
    fake_kafka.Consumer = lambda _config: fake_consumer
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_kafka)
    monkeypatch.setattr(
        module,
        "load_client_settings",
        lambda _servers: SimpleNamespace(to_dict=lambda: {}),
    )
    monkeypatch.setattr(module, "KafkaBus", lambda _servers: Mock())
    monkeypatch.setattr(module, "Thread", InlineThread)
    monkeypatch.setattr(module.Event, "wait", lambda _self, timeout=None: False)

    with pytest.raises(RetryableMessageError, match="assignment"):
        module.RateLimitClient("broker:9093", "worker")


def test_acquire_returns_when_permit_is_granted():
    client = make_client()
    client.bus.publish.side_effect = respond_to_request(client, {"granted": True})

    assert client.acquire("cms:account") is None

    topic, request = client.bus.publish.call_args.args[:2]
    assert topic == module.RATE_LIMIT_REQUESTS
    assert request.command == "acquire_permit"
    assert request.payload == {"bucket": "cms:account"}
    assert request.reply_to == module.RATE_LIMIT_RESPONSES
    assert request.correlation_id
    assert client._pending == {}


def test_acquire_waits_then_retries_after_denied_permit(monkeypatch):
    client = make_client()
    delays = []
    monkeypatch.setattr(module, "sleep", delays.append)
    callbacks = [
        respond_to_request(client, {"granted": False, "retry_after_ms": 1250}),
        respond_to_request(client, {"granted": True}),
    ]

    def publish(*args, **kwargs):
        return callbacks.pop(0)(*args, **kwargs)

    client.bus.publish.side_effect = publish

    client.acquire("google:sheets")

    assert delays == [1.25]
    assert client.bus.publish.call_count == 2


@pytest.mark.parametrize(
    "error", ["RATE_LIMIT_BACKEND_UNAVAILABLE: Redis", "other failure"]
)
def test_acquire_translates_server_error(error):
    client = make_client()
    client.bus.publish.side_effect = respond_to_request(client, error=error)

    expected = (
        RetryableMessageError
        if error.startswith("RATE_LIMIT_BACKEND")
        else RemoteServiceError
    )
    with pytest.raises(expected):
        client.acquire("cms:account")


@pytest.mark.parametrize("delay", [True, -1, "bad"])
def test_acquire_rejects_invalid_retry_delay(delay):
    client = make_client()
    client.bus.publish.side_effect = respond_to_request(
        client, {"granted": False, "retry_after_ms": delay}
    )

    with pytest.raises(RemoteServiceError, match="invalid delay"):
        client.acquire("cms:account")


def test_acquire_removes_pending_request_after_publish_failure():
    client = make_client()
    client.bus.publish.side_effect = RuntimeError("broker down")

    with pytest.raises(RetryableMessageError, match="Could not send"):
        client.acquire("cms:account")

    assert client._pending == {}


def test_acquire_removes_pending_request_after_timeout():
    client = make_client(timeout=0)

    with pytest.raises(RetryableMessageError, match="did not answer"):
        client.acquire("cms:account")

    assert client._pending == {}


def test_listener_routes_correlated_response_and_skips_kafka_error_records(
    monkeypatch,
):
    eof = SimpleNamespace(code=lambda: -191)
    broker_error = SimpleNamespace(code=lambda: 2, __str__=lambda self: "broker error")
    correlation_id = "expected-correlation"
    response = Envelope.create(
        "response", {"granted": True}, correlation_id=correlation_id
    )
    consumer = FakeConsumer(
        [
            FakeMessage(error=eof),
            FakeMessage(error=broker_error),
            FakeMessage(Envelope.create("response", {}, correlation_id="other")),
            FakeMessage(response),
            RuntimeError("stop listener"),
        ]
    )
    fake_kafka = ModuleType("confluent_kafka")
    fake_kafka.KafkaError = SimpleNamespace(_PARTITION_EOF=-191)
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_kafka)
    client = make_client()
    client._consumer = consumer
    client._ready = threading.Event()
    waiting_event = threading.Event()
    results = []
    client._pending[correlation_id] = (waiting_event, results)

    client._listen()

    assert waiting_event.is_set()
    assert results == [response]
    assert len(consumer.commits) == 2
    assert client._ready.is_set()


def test_listener_stops_and_marks_ready_when_poll_raises(monkeypatch):
    fake_kafka = ModuleType("confluent_kafka")
    fake_kafka.KafkaError = SimpleNamespace(_PARTITION_EOF=-191)
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_kafka)
    client = make_client()
    client._consumer = FakeConsumer([RuntimeError("consumer stopped")])
    client._ready = threading.Event()

    client._listen()

    assert client._ready.is_set()


def test_listener_marks_ready_after_assignment_and_empty_poll(monkeypatch):
    fake_kafka = ModuleType("confluent_kafka")
    fake_kafka.KafkaError = SimpleNamespace(_PARTITION_EOF=-191)
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_kafka)
    consumer = FakeConsumer([None, RuntimeError("stop listener")])
    client = make_client()
    client._consumer = consumer
    client._ready = threading.Event()

    client._listen()

    assert client._ready.is_set()

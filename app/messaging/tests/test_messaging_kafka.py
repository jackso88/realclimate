"""Unit tests for Kafka transport helpers using a fake broker client."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.messaging import kafka
from app.messaging.exceptions import RemoteServiceError, RequestTimeoutError
from app.messaging.models import Envelope


class FakeError:
    """Represent a Kafka error returned by a fake message."""

    def __init__(self, message="broker failure", code=1):
        self.message = message
        self._code = code

    def str(self):
        return self.message

    def code(self):
        return self._code


class FakeMessage:
    """Represent a consumed Kafka record."""

    def __init__(self, value=b"", error=None):
        self._value = value
        self._error = error

    def value(self):
        return self._value

    def error(self):
        return self._error


class FakeProducer:
    """Record produced messages and emulate producer acknowledgements."""

    def __init__(self, config):
        self.config = config
        self.produced = []
        self.remaining = 0
        self.polled = []

    def produce(self, topic, **kwargs):
        self.produced.append((topic, kwargs))

    def poll(self, timeout):
        self.polled.append(timeout)

    def flush(self, timeout):
        return self.remaining


class FakeConsumer:
    """Provide scripted consumer results and record lifecycle calls."""

    def __init__(self, config, *, messages=(), watermarks=(0, 0)):
        self.config = config
        self.messages = list(messages)
        self.watermarks = watermarks
        self.subscriptions = []
        self.assignments = []
        self.commits = []
        self.closed = False

    def subscribe(self, topics):
        self.subscriptions.append(topics)

    def assignment(self):
        return [object()]

    def poll(self, timeout):
        if self.messages:
            result = self.messages.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return None

    def get_watermark_offsets(self, topic_partition, timeout):
        return self.watermarks

    def assign(self, partitions):
        self.assignments.append(partitions)

    def commit(self, **kwargs):
        self.commits.append(kwargs)

    def close(self):
        self.closed = True


@pytest.fixture
def kafka_clients(monkeypatch):
    """Install fake confluent_kafka constructors and return their instances."""
    producer = FakeProducer({})
    consumers = [FakeConsumer({})]

    def make_consumer(config):
        consumers[0].config = config
        return consumers[0]

    fake_module = ModuleType("confluent_kafka")

    def make_producer(config):
        producer.config = config
        return producer

    fake_module.Producer = make_producer
    fake_module.Consumer = make_consumer
    fake_module.TopicPartition = lambda *args: args
    fake_module.KafkaError = SimpleNamespace(_PARTITION_EOF=-191)
    monkeypatch.setitem(sys.modules, "confluent_kafka", fake_module)
    monkeypatch.setattr(
        kafka,
        "load_client_settings",
        lambda servers: SimpleNamespace(
            to_dict=lambda: {
                "bootstrap.servers": servers,
                "security.protocol": "SASL_SSL",
            }
        ),
    )
    return producer, consumers


def test_sanitize_error_redacts_credentials():
    sanitized = kafka.sanitize_error("access=u%3Bsecret&token=abc password=hidden")

    assert sanitized == "access=<redacted>&token=<redacted> password=<redacted>"


def test_publish_serializes_message_and_uses_utf8_key(kafka_clients):
    producer, _ = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    message = Envelope.create("run", {"value": 1})

    bus.publish("jobs", message, key="ключ")

    topic, record = producer.produced[0]
    assert topic == "jobs"
    assert record["key"] == "ключ".encode()
    assert Envelope.decode(record["value"]) == message
    assert producer.config["message.max.bytes"] == 80_000_000
    assert producer.polled == [0]


def test_publish_raises_when_broker_does_not_acknowledge(kafka_clients):
    producer, _ = kafka_clients
    producer.remaining = 1

    with pytest.raises(RuntimeError, match="did not acknowledge"):
        kafka.KafkaBus("broker:9093").publish("jobs", Envelope.create("run"))


def test_read_latest_returns_none_for_empty_partition(kafka_clients):
    _, consumers = kafka_clients
    bus = kafka.KafkaBus("broker:9093")

    assert bus.read_latest("state") is None
    assert consumers[0].closed


def test_read_latest_decodes_latest_partition_record(kafka_clients):
    _, consumers = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    expected = Envelope.create("state", {"ready": True})
    consumers[0].messages.append(FakeMessage(expected.encode()))
    consumers[0].watermarks = (0, 4)

    assert bus.read_latest("state", partition=2) == expected
    assert consumers[0].assignments == [[("state", 2, 3)]]
    assert consumers[0].closed


def test_read_latest_returns_none_when_partition_poll_is_empty(kafka_clients):
    _, consumers = kafka_clients
    consumer = consumers[0]
    consumer.watermarks = (0, 1)

    assert kafka.KafkaBus("broker:9093").read_latest("state") is None
    assert consumer.closed


def test_read_latest_raises_for_kafka_error(kafka_clients):
    _, consumers = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    consumers[0].messages.append(FakeMessage(error=FakeError("read failed")))
    consumers[0].watermarks = (0, 1)

    with pytest.raises(RuntimeError, match="read failed"):
        bus.read_latest("state")
    assert consumers[0].closed


def test_request_waits_for_matching_response_and_ignores_other_correlation(
    kafka_clients, monkeypatch
):
    producer, consumers = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    response_values = [
        FakeMessage(error=FakeError("end", code=-191)),
        FakeMessage(
            Envelope.create(
                "response", {"stale": True}, correlation_id="wrong"
            ).encode()
        ),
    ]
    consumer = FakeConsumer({})
    monkeypatch.setattr(
        sys.modules["confluent_kafka"], "Consumer", lambda _config: consumer
    )

    def publish_request(_topic, request, key=None):
        response_values.append(
            Envelope.create(
                "response", {"ok": True}, correlation_id=request.correlation_id
            )
        )

    bus.publish = publish_request

    def poll(_timeout):
        if response_values:
            item = response_values.pop(0)
            return item if isinstance(item, FakeMessage) else FakeMessage(item.encode())
        return None

    consumer.poll = poll
    result = bus.request(
        "requests", "responses", "run", {}, timeout=0.2, response_group="test"
    )

    assert result.payload == {"ok": True}
    assert producer.produced == []
    assert consumer.subscriptions == [["responses"]]
    assert consumer.closed


def test_request_raises_remote_error_and_closes_consumer(kafka_clients, monkeypatch):
    _, consumers = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    consumer = FakeConsumer({})
    monkeypatch.setattr(
        sys.modules["confluent_kafka"], "Consumer", lambda _config: consumer
    )

    def publish_request(_topic, request, key=None):
        consumer.messages.append(
            FakeMessage(
                Envelope.create(
                    "response",
                    correlation_id=request.correlation_id,
                    error="access=secret denied",
                ).encode()
            )
        )

    bus.publish = publish_request

    with pytest.raises(RemoteServiceError, match="access=<redacted>"):
        bus.request(
            "requests", "responses", "run", {}, timeout=0.2, response_group="test"
        )
    assert consumer.closed


def test_request_times_out_and_closes_consumer(kafka_clients, monkeypatch):
    _, consumers = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    consumer = FakeConsumer({})
    monkeypatch.setattr(
        sys.modules["confluent_kafka"], "Consumer", lambda _config: consumer
    )

    with pytest.raises(RequestTimeoutError):
        bus.request(
            "requests", "responses", "run", {}, timeout=0, response_group="test"
        )
    assert consumer.closed


def test_publish_reply_skips_requests_without_reply_topic(kafka_clients):
    producer, _ = kafka_clients
    bus = kafka.KafkaBus("broker:9093")

    kafka.publish_reply(bus, Envelope.create("run"), {"ok": True})

    assert producer.produced == []


def test_publish_reply_correlates_and_redacts_error(kafka_clients):
    producer, _ = kafka_clients
    bus = kafka.KafkaBus("broker:9093")
    request = Envelope.create("run", correlation_id="corr", reply_to="responses")

    kafka.publish_reply(bus, request, error="access=secret")

    topic, record = producer.produced[0]
    response = Envelope.decode(record["value"])
    assert topic == "responses"
    assert record["key"] == b"corr"
    assert response.correlation_id == "corr"
    assert response.error == "access=<redacted>"


def test_publish_failure_sends_sanitized_notification(kafka_clients):
    producer, _ = kafka_clients
    bus = kafka.KafkaBus("broker:9093")

    kafka.publish_failure(bus, "worker", ValueError("password=secret"))

    _, record = producer.produced[0]
    notification = Envelope.decode(record["value"])
    assert notification.command == "failure"
    assert notification.payload == {
        "service": "worker",
        "error_type": "ValueError",
        "error": "password=<redacted>",
    }


def test_run_consumer_dispatches_commits_and_closes_on_shutdown(
    kafka_clients, monkeypatch
):
    _, consumers = kafka_clients
    message = Envelope.create("run", {"n": 1})
    consumer = FakeConsumer(
        {}, messages=[FakeMessage(message.encode()), KeyboardInterrupt()]
    )
    monkeypatch.setattr(
        sys.modules["confluent_kafka"], "Consumer", lambda _config: consumer
    )
    handled = []

    with pytest.raises(KeyboardInterrupt):
        kafka.run_consumer(
            "broker:9093",
            "jobs",
            "worker",
            lambda envelope, _bus: handled.append(envelope),
        )

    assert handled == [message]
    assert len(consumer.commits) == 1
    assert consumer.commits[0]["message"].value() == message.encode()
    assert consumer.closed


def test_run_consumer_commits_message_when_handler_fails(kafka_clients, monkeypatch):
    _, consumers = kafka_clients
    message = Envelope.create("run")
    consumer = FakeConsumer(
        {}, messages=[FakeMessage(message.encode()), KeyboardInterrupt()]
    )
    monkeypatch.setattr(
        sys.modules["confluent_kafka"], "Consumer", lambda _config: consumer
    )

    def handler(_envelope, _bus):
        raise ValueError("handler failed")

    with pytest.raises(KeyboardInterrupt):
        kafka.run_consumer("broker:9093", "jobs", "worker", handler)

    assert len(consumer.commits) == 1
    assert consumer.closed


def test_run_consumer_raises_on_non_eof_kafka_error_and_closes(
    kafka_clients, monkeypatch
):
    _, consumers = kafka_clients
    consumer = FakeConsumer(
        {}, messages=[FakeMessage(error=FakeError("consumer failed"))]
    )
    monkeypatch.setattr(
        sys.modules["confluent_kafka"], "Consumer", lambda _config: consumer
    )

    with pytest.raises(RuntimeError, match="consumer failed"):
        kafka.run_consumer(
            "broker:9093", "jobs", "worker", lambda _envelope, _bus: None
        )

    assert consumer.closed

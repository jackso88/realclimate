"""Fake confluent_kafka clients and the fixtures that install them."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.messaging import kafka


class FakeMessage:
    """Represent a consumed Kafka record."""

    def __init__(self, value=b"", error=None):
        self._value = value
        self._error = error

    def value(self):
        return self._value

    def error(self):
        return self._error

    def topic(self):
        return "jobs"

    def partition(self):
        return 0

    def offset(self):
        return 4


class RecordingProducer:
    """Remember produced records and acknowledge every flush."""

    def __init__(self, events):
        self.events = events
        self.produced = []

    def produce(self, topic, **kwargs):
        self.events.append("produce")
        self.produced.append((topic, kwargs))

    def poll(self, timeout):
        return 0

    def flush(self, timeout):
        return 0


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
        self.seeks = []
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

    def seek(self, partition):
        self.seeks.append(partition)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_kafka(monkeypatch):
    """Install a fake confluent_kafka module; tests assign ``state.consumer``."""
    events = []
    state = SimpleNamespace(
        events=events,
        producer=RecordingProducer(events),
        consumer=None,
        consumer_configs=[],
    )

    def make_consumer(config):
        state.consumer_configs.append(config)
        return state.consumer

    def load_settings(servers):
        return SimpleNamespace(to_dict=lambda: {"bootstrap.servers": servers})

    module = ModuleType("confluent_kafka")
    module.Producer = lambda config: state.producer
    module.Consumer = make_consumer
    module.TopicPartition = lambda *args: args
    module.KafkaError = SimpleNamespace(_PARTITION_EOF=-191)
    monkeypatch.setitem(sys.modules, "confluent_kafka", module)
    monkeypatch.setattr(kafka, "load_client_settings", load_settings)
    return state


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

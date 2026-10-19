"""Tests for the RPC wait loop and the worker loop of the Kafka bus."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

from app.messaging import kafka
from app.messaging.exceptions import RetryableMessageError
from app.contracts.models import Envelope


class StopLoop(Exception):
    """Raised by a scripted consumer to break out of an endless worker loop."""


class FakeKafkaError:
    """Represent an error object attached to a consumed record."""

    def __init__(self, code=1, text="broker failure"):
        self._code = code
        self._text = text

    def code(self):
        return self._code

    def str(self):
        return self._text


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


class ScriptedConsumer:
    """Replay scripted poll results, then raise StopLoop.

    The first ``assignment_after`` polls model the delay before Kafka assigns
    partitions: they return nothing and do not consume the script.
    """

    def __init__(self, script, events, assignment_after=0):
        self.script = list(script)
        self.events = events
        self.assignment_after = assignment_after
        self.polls = 0
        self.commits = []
        self.seeks = []
        self.subscriptions = []
        self.closed = False

    def subscribe(self, topics):
        self.subscriptions.append(topics)

    def assignment(self):
        return [object()] if self.polls >= self.assignment_after else []

    def poll(self, timeout):
        self.events.append("poll")
        self.polls += 1
        if self.polls <= self.assignment_after:
            return None
        if not self.script:
            raise StopLoop
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item() if callable(item) else item

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


def reply_to_request(state, payload=None, correlation_id=None):
    """Return a script entry that answers the most recent produced request."""

    def build():
        request = Envelope.decode(state.producer.produced[-1][1]["value"])
        reply = Envelope.create(
            "response",
            payload or {},
            correlation_id=correlation_id or request.correlation_id,
        )
        return FakeMessage(reply.encode())

    return build


def make_request(bus):
    return bus.request(
        "requests",
        "responses",
        "do_work",
        {"a": 1},
        timeout=5,
        response_group="group",
    )


def test_request_waits_for_partition_assignment_before_publishing(fake_kafka):
    reply = reply_to_request(fake_kafka, {"ok": True})
    fake_kafka.consumer = ScriptedConsumer(
        [reply], fake_kafka.events, assignment_after=2
    )

    response = make_request(kafka.KafkaBus("kafka:9092"))

    assert response.payload == {"ok": True}
    assert fake_kafka.events[:4] == ["poll", "poll", "produce", "poll"]


def test_request_skips_empty_polls_and_replies_for_other_requests(fake_kafka):
    foreign = Envelope.create("response", {}, correlation_id="someone-else")
    reply = reply_to_request(fake_kafka, {"ok": True})
    fake_kafka.consumer = ScriptedConsumer(
        [None, FakeMessage(foreign.encode()), reply], fake_kafka.events
    )

    response = make_request(kafka.KafkaBus("kafka:9092"))

    assert response.payload == {"ok": True}
    assert fake_kafka.consumer.commits == [{"asynchronous": False}]
    assert fake_kafka.consumer.closed


def test_request_ignores_partition_eof_markers(fake_kafka):
    eof = FakeMessage(error=FakeKafkaError(code=-191))
    reply = reply_to_request(fake_kafka, {"ok": True})
    fake_kafka.consumer = ScriptedConsumer([eof, reply], fake_kafka.events)

    response = make_request(kafka.KafkaBus("kafka:9092"))

    assert response.payload == {"ok": True}


def test_request_raises_on_a_real_consumer_error_and_closes(fake_kafka):
    failure = FakeMessage(error=FakeKafkaError(code=5, text="topic unavailable"))
    fake_kafka.consumer = ScriptedConsumer([failure], fake_kafka.events)

    with pytest.raises(RuntimeError, match="topic unavailable"):
        make_request(kafka.KafkaBus("kafka:9092"))

    assert fake_kafka.consumer.closed
    assert fake_kafka.consumer.commits == []


def test_run_consumer_dispatches_each_record_and_commits_it(fake_kafka):
    first = Envelope.create("ping", {"n": 1})
    second = Envelope.create("ping", {"n": 2})
    fake_kafka.consumer = ScriptedConsumer(
        [FakeMessage(first.encode()), FakeMessage(second.encode())],
        fake_kafka.events,
    )
    seen = []

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092",
            "jobs",
            "worker-group",
            lambda envelope, bus: seen.append((envelope.payload, bus)),
        )

    assert [payload for payload, _ in seen] == [{"n": 1}, {"n": 2}]
    assert all(isinstance(bus, kafka.KafkaBus) for _, bus in seen)
    assert fake_kafka.consumer.subscriptions == [["jobs"]]
    assert len(fake_kafka.consumer.commits) == 2
    assert fake_kafka.consumer.commits[0]["asynchronous"] is False
    assert fake_kafka.consumer.closed


def test_run_consumer_uses_manual_commits_and_the_given_group(fake_kafka):
    fake_kafka.consumer = ScriptedConsumer([], fake_kafka.events)

    with pytest.raises(StopLoop):
        kafka.run_consumer("kafka:9092", "jobs", "worker-group", lambda *_: None)

    config = fake_kafka.consumer_configs[0]
    assert config["group.id"] == "worker-group"
    assert config["enable.auto.commit"] is False
    assert config["auto.offset.reset"] == "earliest"


def test_run_consumer_skips_empty_polls_and_partition_eof(fake_kafka):
    eof = FakeMessage(error=FakeKafkaError(code=-191))
    record = FakeMessage(Envelope.create("ping").encode())
    fake_kafka.consumer = ScriptedConsumer([None, eof, record], fake_kafka.events)
    handled = []

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092", "jobs", "group", lambda envelope, bus: handled.append(1)
        )

    assert handled == [1]
    assert len(fake_kafka.consumer.commits) == 1


def test_run_consumer_stops_on_a_real_consumer_error(fake_kafka):
    failure = FakeMessage(error=FakeKafkaError(code=5, text="coordinator lost"))
    fake_kafka.consumer = ScriptedConsumer([failure], fake_kafka.events)

    with pytest.raises(RuntimeError, match="coordinator lost"):
        kafka.run_consumer("kafka:9092", "jobs", "group", lambda *_: None)

    assert fake_kafka.consumer.closed


def test_run_consumer_runs_a_heartbeat_for_named_services(monkeypatch, fake_kafka):
    created = []

    class FakeReporter:
        def __init__(self, bus, service):
            self.bus = bus
            self.service = service
            self.calls = []
            created.append(self)

        def start(self):
            self.calls.append("start")

        def stop(self):
            self.calls.append("stop")

    monkeypatch.setattr("app.messaging.health.HeartbeatReporter", FakeReporter)
    fake_kafka.consumer = ScriptedConsumer([], fake_kafka.events)

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092", "jobs", "group", lambda *_: None, service_name="core"
        )

    assert len(created) == 1
    assert created[0].service == "core"
    assert isinstance(created[0].bus, kafka.KafkaBus)
    assert created[0].calls == ["start", "stop"]


def test_run_consumer_has_no_heartbeat_without_a_service_name(monkeypatch, fake_kafka):
    created = []
    monkeypatch.setattr(
        "app.messaging.health.HeartbeatReporter",
        lambda bus, service: created.append(service),
    )
    fake_kafka.consumer = ScriptedConsumer([], fake_kafka.events)

    with pytest.raises(StopLoop):
        kafka.run_consumer("kafka:9092", "jobs", "group", lambda *_: None)

    assert created == []


class RecordingReporter:
    """Record busy/idle marks together with handler and commit events."""

    events = None

    def __init__(self, bus, service):
        self.service = service

    def start(self):
        pass

    def stop(self):
        pass

    def mark_busy(self):
        RecordingReporter.events.append("busy")

    def mark_idle(self):
        RecordingReporter.events.append("idle")


def install_recording_reporter(monkeypatch, events):
    RecordingReporter.events = events
    monkeypatch.setattr("app.messaging.health.HeartbeatReporter", RecordingReporter)


def test_worker_is_marked_busy_only_while_the_handler_runs(monkeypatch, fake_kafka):
    events = fake_kafka.events
    install_recording_reporter(monkeypatch, events)
    record = FakeMessage(Envelope.create("ping").encode())
    fake_kafka.consumer = ScriptedConsumer([record], events)
    original_commit = fake_kafka.consumer.commit

    def recording_commit(**kwargs):
        events.append("commit")
        original_commit(**kwargs)

    fake_kafka.consumer.commit = recording_commit

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092",
            "jobs",
            "group",
            lambda envelope, bus: events.append("handle"),
            service_name="core",
        )

    interesting = [event for event in events if event != "poll"]
    assert interesting == ["busy", "handle", "idle", "commit"]


def test_worker_is_marked_idle_even_when_the_handler_fails(monkeypatch, fake_kafka):
    events = fake_kafka.events
    install_recording_reporter(monkeypatch, events)
    record = FakeMessage(Envelope.create("ping").encode())
    fake_kafka.consumer = ScriptedConsumer([record], events)
    monkeypatch.setattr(kafka, "sleep", lambda _seconds: None)

    def failing_handler(envelope, bus):
        raise RetryableMessageError("redis unavailable")

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092", "jobs", "group", failing_handler, service_name="core"
        )

    interesting = [event for event in events if event != "poll"]
    assert interesting == ["busy", "idle"]
    assert fake_kafka.consumer.commits == []
    assert fake_kafka.consumer.seeks == [("jobs", 0, 4)]


def test_retry_backoff_grows_exponentially(monkeypatch, fake_kafka):
    record = FakeMessage(Envelope.create("ping").encode())
    fake_kafka.consumer = ScriptedConsumer([record] * 5, fake_kafka.events)
    delays = []
    monkeypatch.setattr(kafka, "sleep", delays.append)

    def failing_handler(envelope, bus):
        raise RetryableMessageError("temporary failure")

    with pytest.raises(StopLoop):
        kafka.run_consumer("kafka:9092", "jobs", "group", failing_handler)

    assert delays == [1, 2, 4, 8, 16]
    assert len(fake_kafka.consumer.seeks) == 5
    assert fake_kafka.consumer.commits == []


def test_unnamed_workers_run_without_any_busy_tracking(fake_kafka):
    record = FakeMessage(Envelope.create("ping").encode())
    fake_kafka.consumer = ScriptedConsumer([record], fake_kafka.events)
    handled = []

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092", "jobs", "group", lambda envelope, bus: handled.append(1)
        )

    assert handled == [1]


def test_poll_interval_defaults_to_one_hour(fake_kafka):
    fake_kafka.consumer = ScriptedConsumer([], fake_kafka.events)

    with pytest.raises(StopLoop):
        kafka.run_consumer("kafka:9092", "jobs", "group", lambda *_: None)

    assert fake_kafka.consumer_configs[0]["max.poll.interval.ms"] == 3_600_000


def test_poll_interval_can_be_raised_for_slow_handlers(fake_kafka):
    fake_kafka.consumer = ScriptedConsumer([], fake_kafka.events)

    with pytest.raises(StopLoop):
        kafka.run_consumer(
            "kafka:9092",
            "jobs",
            "group",
            lambda *_: None,
            max_poll_interval_ms=5_100_000,
        )

    assert fake_kafka.consumer_configs[0]["max.poll.interval.ms"] == 5_100_000


def test_request_consumers_use_the_default_poll_interval(fake_kafka):
    reply = reply_to_request(fake_kafka, {"ok": True})
    fake_kafka.consumer = ScriptedConsumer([reply], fake_kafka.events)

    make_request(kafka.KafkaBus("kafka:9092"))

    config = fake_kafka.consumer_configs[0]
    assert config["max.poll.interval.ms"] == kafka.DEFAULT_MAX_POLL_INTERVAL_MS

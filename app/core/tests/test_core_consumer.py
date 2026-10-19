"""Tests for the core's two-event Redis pairing and processing contract."""

from app.contracts.models import Envelope
from app.core import consumer
from app.core.models import CorePipelineOutput, CoreSettings
from app.messaging.payloads import decode_bytes, encode_bytes
from app.messaging.topics import (
    CORE_DUPLICATE_MAP_STATE,
    CORE_NOTIFICATIONS,
    CORE_PROCESS_RESULTS,
    CURRENT_DOWNLOADS,
    REFERENCE_DOWNLOADS,
    REFERENCE_PIPELINE_COMPLETED,
)


class FakeBus:
    def __init__(self, state=None):
        self.state = state
        self.published = []

    def read_latest(self, topic):
        assert topic == CORE_DUPLICATE_MAP_STATE
        return self.state

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))


class FakePendingInputs:
    def __init__(self):
        self.parts = {}
        self.claimed = set()
        self.completed = []
        self.released = []
        self.done = set()

    def is_completed(self, correlation_id):
        return correlation_id in self.done

    def save_reference(self, correlation_id, content, sha256, claim_token):
        self.parts.setdefault(correlation_id, {})["reference"] = (content, sha256)
        return self._claim(correlation_id, claim_token)

    def save_current(self, correlation_id, content, claim_token):
        self.parts.setdefault(correlation_id, {})["current"] = content
        return self._claim(correlation_id, claim_token)

    def _claim(self, correlation_id, claim_token):
        parts = self.parts[correlation_id]
        if set(parts) != {"reference", "current"} or correlation_id in self.claimed:
            return False
        self.claimed.add(correlation_id)
        self.tokens = getattr(self, "tokens", {})
        self.tokens[correlation_id] = claim_token
        return True

    def get_pair(self, correlation_id):
        reference, digest = self.parts[correlation_id]["reference"]
        return reference, self.parts[correlation_id]["current"], digest

    def complete(self, correlation_id, token):
        self.completed.append(correlation_id)
        assert self.tokens[correlation_id] == token
        self.parts.pop(correlation_id)
        self.claimed.discard(correlation_id)
        self.done.add(correlation_id)
        return True

    def release(self, correlation_id, token):
        self.released.append((correlation_id, token))
        self.claimed.discard(correlation_id)


def make_reference(correlation_id="pipeline-1", content=b"reference", digest="digest"):
    return Envelope.create(
        "reference_downloaded",
        {
            "reference_csv_gzip_base64": encode_bytes(content),
            "reference_sha256": digest,
        },
        correlation_id=correlation_id,
    )


def make_current(correlation_id="pipeline-1", content=b"current"):
    return Envelope.create(
        "current_downloaded",
        {"current_csv_gzip_base64": encode_bytes(content)},
        correlation_id=correlation_id,
    )


def make_output(changes=None):
    return CorePipelineOutput(
        processed_csv=b"processed",
        excluded_csv=b"excluded",
        detailed_changes=changes or [],
        updated_duplicate_map={("code", "model", 1): "code-D01"},
    )


def test_core_waits_for_both_correlated_events_and_processes_them(
    monkeypatch, tmp_path
):
    received = []
    monkeypatch.setattr(
        consumer,
        "process_catalogue",
        lambda reference, current, duplicate_map: (
            received.append((reference, current, duplicate_map))
            or make_output(["Added"])
        ),
    )
    monkeypatch.setattr(consumer, "encode_duplicate_map", lambda _: {"entries": []})
    settings = CoreSettings(excluded_csv_path=tmp_path / "excluded.csv")
    bus = FakeBus()
    pending = FakePendingInputs()

    consumer.handle_process(make_reference(), bus, settings, pending)

    assert received == []
    assert bus.published == []

    consumer.handle_process(make_current(), bus, settings, pending)

    assert received == [(b"reference", b"current", consumer.DUPLICATE_CODE_MAP)]
    assert (tmp_path / "excluded.csv").read_bytes() == b"excluded"
    result = next(
        event[1] for event in bus.published if event[0] == CORE_PROCESS_RESULTS
    )
    assert result.correlation_id == "pipeline-1"
    assert result.payload["reference_sha256"] == "digest"
    assert decode_bytes(result.payload["processed_csv_gzip_base64"]) == b"processed"
    assert pending.completed == ["pipeline-1"]
    assert "pipeline-1" not in pending.parts


def test_core_processes_inputs_when_current_arrives_first(monkeypatch, tmp_path):
    processed = []
    monkeypatch.setattr(
        consumer,
        "process_catalogue",
        lambda reference, current, mapping: processed.append((reference, current))
        or make_output(),
    )
    monkeypatch.setattr(consumer, "encode_duplicate_map", lambda _: {"entries": []})
    settings = CoreSettings(excluded_csv_path=tmp_path / "excluded.csv")
    bus = FakeBus()
    pending = FakePendingInputs()

    consumer.handle_process(make_current(), bus, settings, pending)
    assert processed == []
    consumer.handle_process(make_reference(), bus, settings, pending)

    assert processed == [(b"reference", b"current")]
    assert pending.completed == ["pipeline-1"]


def test_core_skips_uploader_and_completes_reference_without_changes(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(consumer, "process_catalogue", lambda *_: make_output())
    monkeypatch.setattr(consumer, "encode_duplicate_map", lambda _: {"entries": []})
    settings = CoreSettings(excluded_csv_path=tmp_path / "excluded.csv")
    bus = FakeBus()
    pending = FakePendingInputs()

    consumer.handle_process(make_reference(), bus, settings, pending)
    consumer.handle_process(make_current(), bus, settings, pending)

    assert all(topic != CORE_NOTIFICATIONS for topic, _, _ in bus.published)
    result = next(
        event[1] for event in bus.published if event[0] == CORE_PROCESS_RESULTS
    )
    assert result.payload["detailed_changes"] == []
    assert "processed_csv_gzip_base64" not in result.payload
    completion = next(
        event[1] for event in bus.published if event[0] == REFERENCE_PIPELINE_COMPLETED
    )
    assert completion.payload == {"reference_sha256": "digest"}
    assert completion.correlation_id == "pipeline-1"


def test_core_consumer_subscribes_to_both_downloaders():
    assert consumer.CORE_INPUT_TOPICS == [REFERENCE_DOWNLOADS, CURRENT_DOWNLOADS]


def test_completed_duplicate_event_is_ignored(monkeypatch, tmp_path):
    process = lambda *_: (_ for _ in ()).throw(AssertionError("must not reprocess"))
    monkeypatch.setattr(consumer, "process_catalogue", process)
    settings = CoreSettings(excluded_csv_path=tmp_path / "excluded.csv")
    pending = FakePendingInputs()
    pending.done.add("pipeline-1")

    consumer.handle_process(make_reference(), FakeBus(), settings, pending)

    assert "pipeline-1" not in pending.parts
    assert pending.completed == []

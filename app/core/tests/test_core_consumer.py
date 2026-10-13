"""Tests for the core request/reply processing contract."""

from app.core.models import CorePipelineOutput
from app.core import consumer
from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes, encode_bytes
from app.messaging.topics import (
    CORE_DUPLICATE_MAP_STATE,
    CORE_NOTIFICATIONS,
    CORE_PROCESS_RESULTS,
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


def test_core_processes_supplied_csv_and_publishes_result(monkeypatch, tmp_path):
    reference_csv = b"reference"
    current_csv = b"current"
    output = CorePipelineOutput(
        processed_csv=b"processed",
        excluded_csv=b"excluded",
        detailed_changes=["Added article X"],
        updated_duplicate_map={("code", "model", 1): "code-D01"},
    )
    process = lambda ref, cur, mapping: output
    monkeypatch.setattr(consumer, "process_catalogue", process)
    monkeypatch.setattr(
        consumer, "encode_duplicate_map", lambda mapping: {"entries": []}
    )
    excluded_path = tmp_path / "excluded.csv"
    monkeypatch.setenv("EXCLUDED_CSV_PATH", str(excluded_path))
    bus = FakeBus()
    reply = []
    monkeypatch.setattr(
        consumer,
        "publish_reply",
        lambda _bus, _message, payload=None, error=None: reply.append((payload, error)),
    )
    monkeypatch.setattr(consumer, "publish_failure", lambda *_: None)
    message = Envelope.create(
        "process_catalogue",
        {
            "reference_csv_gzip_base64": encode_bytes(reference_csv),
            "current_csv_gzip_base64": encode_bytes(current_csv),
            "reference_sha256": "digest",
        },
        correlation_id="test-run",
        reply_to="core.process.results",
    )

    consumer.handle_process(message, bus)

    assert excluded_path.read_bytes() == b"excluded"
    state_event = next(
        event for event in bus.published if event[0] == CORE_DUPLICATE_MAP_STATE
    )
    result_event = next(
        event for event in bus.published if event[0] == CORE_PROCESS_RESULTS
    )
    notification = next(
        event for event in bus.published if event[0] == CORE_NOTIFICATIONS
    )
    assert state_event[2] == "duplicate-map"
    assert result_event[1].payload["reference_sha256"] == "digest"
    assert (
        decode_bytes(result_event[1].payload["processed_csv_gzip_base64"])
        == b"processed"
    )
    assert notification[1].payload["changes"] == ["Added article X"]
    assert result_event[1].correlation_id == "test-run"
    assert result_event[1].payload["changes_count"] == 1


def test_core_does_not_publish_empty_change_notification(monkeypatch, tmp_path):
    output = CorePipelineOutput(b"processed", b"excluded", [], {})
    monkeypatch.setattr(consumer, "process_catalogue", lambda *_: output)
    monkeypatch.setattr(consumer, "encode_duplicate_map", lambda _: {"entries": []})
    monkeypatch.setenv("EXCLUDED_CSV_PATH", str(tmp_path / "excluded.csv"))
    monkeypatch.setattr(consumer, "publish_reply", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(consumer, "publish_failure", lambda *_: None)
    bus = FakeBus()
    message = Envelope.create(
        "process_catalogue",
        {
            "reference_csv_gzip_base64": encode_bytes(b"ref"),
            "current_csv_gzip_base64": encode_bytes(b"current"),
        },
    )

    consumer.handle_process(message, bus)

    assert all(topic != CORE_NOTIFICATIONS for topic, _, _ in bus.published)

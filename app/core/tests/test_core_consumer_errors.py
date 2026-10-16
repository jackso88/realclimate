"""Tests for the core worker's failure handling, state fallback and wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.core import consumer
from app.core.models import CorePipelineOutput
from app.core.pipeline import encode_duplicate_map
from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import CORE_PROCESS_REQUESTS


class FakeBus:
    """Return an optional stored duplicate-map state and record publishes."""

    def __init__(self, state=None):
        self.state = state
        self.published = []

    def read_latest(self, topic):
        return self.state

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))


def make_request(command="process_catalogue", **payload):
    payload.setdefault("reference_csv_gzip_base64", encode_bytes(b"reference"))
    payload.setdefault("current_csv_gzip_base64", encode_bytes(b"current"))
    return Envelope.create(command, payload, correlation_id="run-1")


def make_output():
    return CorePipelineOutput(
        processed_csv=b"processed",
        excluded_csv=b"excluded",
        detailed_changes=[],
        updated_duplicate_map={("a", "m", 1): "a"},
    )


@pytest.fixture
def core(monkeypatch, tmp_path):
    """Replace the pipeline and reply helpers; return handles to inspect them."""
    parts = SimpleNamespace(
        process=Mock(return_value=make_output()),
        failure=Mock(),
        reply=Mock(),
    )
    monkeypatch.setattr(consumer, "process_catalogue", parts.process)
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    monkeypatch.setattr(consumer, "publish_reply", parts.reply)
    monkeypatch.setenv("EXCLUDED_CSV_PATH", str(tmp_path / "excluded.csv"))
    return parts


def test_unsupported_commands_are_rejected_and_reported(core):
    bus = FakeBus()
    request = make_request(command="drop_database")

    consumer.handle_process(request, bus)

    core.process.assert_not_called()
    assert bus.published == []
    error = core.failure.call_args.args[2]
    assert str(error) == "Unsupported core command: drop_database"
    core.reply.assert_called_once_with(
        bus, request, error="Unsupported core command: drop_database"
    )


def test_a_pipeline_failure_alerts_the_admin_and_replies_with_the_error(core):
    failure = RuntimeError("merge exploded")
    core.process.side_effect = failure
    bus = FakeBus()
    request = make_request()

    consumer.handle_process(request, bus)

    core.failure.assert_called_once_with(bus, "core", failure)
    core.reply.assert_called_once_with(bus, request, error="merge exploded")


def test_a_failed_run_does_not_advance_the_persisted_duplicate_state(core):
    core.process.side_effect = RuntimeError("merge exploded")
    bus = FakeBus()

    consumer.handle_process(make_request(), bus)

    assert bus.published == []


def test_a_missing_input_is_reported_instead_of_crashing_the_worker(core):
    bus = FakeBus()
    request = Envelope.create("process_catalogue", {}, correlation_id="run-1")

    consumer.handle_process(request, bus)

    core.process.assert_not_called()
    assert "reference_csv_gzip_base64" in core.reply.call_args.kwargs["error"]


def test_the_bundled_mapping_is_used_when_no_state_exists_yet(core, monkeypatch):
    bundled = {("seed", "model", 1): "seed"}
    monkeypatch.setattr(consumer, "DUPLICATE_CODE_MAP", bundled)

    consumer.handle_process(make_request(), FakeBus(state=None))

    assert core.process.call_args.args[2] == bundled


def test_the_persisted_state_wins_over_the_bundled_mapping(core, monkeypatch):
    monkeypatch.setattr(consumer, "DUPLICATE_CODE_MAP", {("seed", "model", 1): "seed"})
    stored = {("code", "model", 1): "code-D01"}
    state = Envelope.create("duplicate_map_state", encode_duplicate_map(stored))

    consumer.handle_process(make_request(), FakeBus(state=state))

    assert core.process.call_args.args[2] == stored


def test_the_excluded_review_file_is_written_to_the_configured_path(core, tmp_path):
    consumer.handle_process(make_request(), FakeBus())

    assert (tmp_path / "excluded.csv").read_bytes() == b"excluded"


def test_the_excluded_file_directory_is_created(core, monkeypatch, tmp_path):
    nested = tmp_path / "deep" / "er" / "excluded.csv"
    monkeypatch.setenv("EXCLUDED_CSV_PATH", str(nested))

    consumer.handle_process(make_request(), FakeBus())

    assert nested.read_bytes() == b"excluded"


def test_main_runs_the_core_worker(monkeypatch):
    run_consumer = Mock()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    consumer.main()

    run_consumer.assert_called_once_with(
        "localhost:9092",
        CORE_PROCESS_REQUESTS,
        "core-service",
        consumer.handle_process,
        service_name="core",
    )

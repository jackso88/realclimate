"""Tests for malformed replies handled by the orchestrator workflow."""

import pytest

from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.orchestrator.models import OrchestratorSettings
from app.orchestrator.runner import run_workflow


class ScriptedBus:
    """Return configured replies in order and record everything else."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.published = []

    def request(self, topic, response_topic, command, payload, **kwargs):
        self.requests.append(topic)
        return self.replies.pop(0)

    def read_latest(self, topic):
        return None

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))


def reply(payload):
    return Envelope.create("response", payload)


def test_non_list_change_report_aborts_before_the_checkpoint():
    bus = ScriptedBus(
        [
            reply({"csv_gzip_base64": encode_bytes(b"reference")}),
            reply({"csv_gzip_base64": encode_bytes(b"current")}),
            reply({"detailed_changes": "not-a-list"}),
        ]
    )

    with pytest.raises(ValueError, match="detailed_changes must be a list"):
        run_workflow(bus, OrchestratorSettings())

    # No uploader call and, crucially, no fingerprint: the run can be retried.
    assert len(bus.requests) == 3
    assert bus.published == []


def test_missing_reference_payload_aborts_before_any_state_change():
    bus = ScriptedBus([reply({})])

    with pytest.raises(KeyError, match="csv_gzip_base64"):
        run_workflow(bus, OrchestratorSettings())

    assert bus.published == []

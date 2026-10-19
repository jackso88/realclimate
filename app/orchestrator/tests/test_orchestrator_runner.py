"""Tests for change-driven workflow orchestration."""

import hashlib

import pytest

from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes, encode_bytes
from app.messaging.topics import (
    CORE_PROCESS_REQUESTS,
    CURRENT_DOWNLOAD_REQUESTS,
    ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE,
    REFERENCE_DOWNLOAD_REQUESTS,
    UPLOADER_REQUESTS,
)
from app.orchestrator.models import OrchestratorSettings
from app.orchestrator.runner import run_workflow


class FakeBus:
    """Small Kafka bus fake that returns configured RPC replies."""

    def __init__(self, responses, state=None, uploader_error=None):
        self.responses = list(responses)
        self.state = state
        self.uploader_error = uploader_error
        self.requests = []
        self.published = []

    def request(self, topic, response_topic, command, payload, **kwargs):
        self.requests.append((topic, response_topic, command, payload, kwargs))
        if topic == UPLOADER_REQUESTS and self.uploader_error:
            raise self.uploader_error
        return self.responses.pop(0)

    def read_latest(self, topic):
        assert topic == ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE
        return self.state

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))


def response(payload):
    return Envelope.create("response", payload)


def settings():
    return OrchestratorSettings(
        request_timeout_seconds=30,
        uploader_timeout_seconds=60,
        instance_id="test-orchestrator",
    )


def test_unchanged_reference_skips_current_core_and_uploader():
    reference_csv = b"supplier,cost\nA,10\n"
    digest = hashlib.sha256(reference_csv).hexdigest()
    bus = FakeBus(
        [response({"csv_gzip_base64": encode_bytes(reference_csv)})],
        state=Envelope.create("reference_fingerprint", {"sha256": digest}),
    )

    result = run_workflow(bus, settings())

    assert result == {
        "status": "skipped",
        "reason": "reference_unchanged",
        "reference_sha256": digest,
        "uploaded": False,
    }
    assert [call[0] for call in bus.requests] == [REFERENCE_DOWNLOAD_REQUESTS]
    assert bus.published == []


def test_changed_reference_runs_core_and_skips_uploader_without_changes():
    reference_csv = b"supplier,cost\nA,10\n"
    current_csv = b"article,price\nA,10\n"
    bus = FakeBus(
        [
            response({"csv_gzip_base64": encode_bytes(reference_csv)}),
            response({"csv_gzip_base64": encode_bytes(current_csv)}),
            response({"detailed_changes": []}),
        ]
    )

    result = run_workflow(bus, settings())

    assert result["status"] == "processed"
    assert result["changes_count"] == 0
    assert result["uploaded"] is False
    assert [call[0] for call in bus.requests] == [
        REFERENCE_DOWNLOAD_REQUESTS,
        CURRENT_DOWNLOAD_REQUESTS,
        CORE_PROCESS_REQUESTS,
    ]
    assert len(bus.published) == 1
    assert bus.published[0][0] == ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE


def test_core_changes_trigger_uploader_and_checkpoint_after_success():
    reference_csv = b"reference bytes"
    current_csv = b"current bytes"
    processed_csv = b"processed bytes"
    changes = ["Added item A"]
    bus = FakeBus(
        [
            response({"csv_gzip_base64": encode_bytes(reference_csv)}),
            response({"csv_gzip_base64": encode_bytes(current_csv)}),
            response(
                {
                    "processed_csv_gzip_base64": encode_bytes(processed_csv),
                    "detailed_changes": changes,
                }
            ),
            response({"cron_num": 9}),
        ]
    )

    result = run_workflow(bus, settings())

    assert result["uploaded"] is True
    assert result["changes_count"] == 1
    assert [call[0] for call in bus.requests] == [
        REFERENCE_DOWNLOAD_REQUESTS,
        CURRENT_DOWNLOAD_REQUESTS,
        CORE_PROCESS_REQUESTS,
        UPLOADER_REQUESTS,
    ]
    core_payload = bus.requests[2][3]
    assert decode_bytes(core_payload["reference_csv_gzip_base64"]) == reference_csv
    assert decode_bytes(core_payload["current_csv_gzip_base64"]) == current_csv
    upload_payload = bus.requests[3][3]
    assert decode_bytes(upload_payload["csv_gzip_base64"]) == processed_csv
    assert bus.published[-1][0] == ORCHESTRATOR_REFERENCE_FINGERPRINT_STATE


def test_failed_upload_does_not_advance_reference_checkpoint():
    reference_csv = b"new reference"
    bus = FakeBus(
        [
            response({"csv_gzip_base64": encode_bytes(reference_csv)}),
            response({"csv_gzip_base64": encode_bytes(b"current")}),
            response(
                {
                    "processed_csv_gzip_base64": encode_bytes(b"processed"),
                    "detailed_changes": ["Updated item"],
                }
            ),
        ],
        uploader_error=RuntimeError("upload failed"),
    )

    with pytest.raises(RuntimeError, match="upload failed"):
        run_workflow(bus, settings())

    assert bus.published == []

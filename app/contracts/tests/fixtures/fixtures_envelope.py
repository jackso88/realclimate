"""Shared fixtures for the envelope tests."""

import json
from datetime import datetime, timezone

import pytest

from app.contracts.models import Envelope


@pytest.fixture
def created_at() -> datetime:
    """A fixed timezone-aware timestamp with microseconds."""
    return datetime(2024, 5, 17, 12, 30, 45, 123456, tzinfo=timezone.utc)


@pytest.fixture
def envelope_data(created_at) -> dict:
    """Valid keyword arguments for building an Envelope directly."""
    return {
        "message_id": "msg-1",
        "command": "acquire_permit",
        "payload": {"bucket": "google:sheets", "nested": {"items": [1, 2, 3]}},
        "correlation_id": "corr-1",
        "reply_to": "rate_limit.responses",
        "error": None,
        "created_at": created_at,
    }


@pytest.fixture
def envelope(envelope_data) -> Envelope:
    """A fully populated, valid envelope."""
    return Envelope(**envelope_data)


@pytest.fixture
def wire_dict(envelope) -> dict:
    """The envelope as a plain JSON-ready dict, easy to corrupt in tests."""
    return json.loads(envelope.encode())


@pytest.fixture
def to_bytes():
    """Return a helper that serializes a dict to UTF-8 JSON bytes."""

    def _to_bytes(data: dict) -> bytes:
        return json.dumps(data).encode("utf-8")

    return _to_bytes

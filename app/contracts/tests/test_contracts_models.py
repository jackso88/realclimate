"""Tests for the Envelope transport model."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.contracts.models import Envelope

# --- Envelope.create --------------------------------------------------------


def test_create_sets_defaults():
    envelope = Envelope.create("ping")

    assert envelope.command == "ping"
    assert envelope.payload == {}
    assert envelope.correlation_id is None
    assert envelope.reply_to is None
    assert envelope.error is None


def test_create_keeps_all_optional_fields():
    envelope = Envelope.create(
        "acquire_permit",
        {"bucket": "telegram:admin_chat"},
        correlation_id="corr-1",
        reply_to="responses",
        error="boom",
    )

    assert envelope.payload == {"bucket": "telegram:admin_chat"}
    assert envelope.correlation_id == "corr-1"
    assert envelope.reply_to == "responses"
    assert envelope.error == "boom"


def test_create_generates_valid_uuid_message_id():
    envelope = Envelope.create("ping")

    assert str(UUID(envelope.message_id)) == envelope.message_id


def test_create_generates_unique_message_ids():
    ids = {Envelope.create("ping").message_id for _ in range(100)}

    assert len(ids) == 100


def test_create_uses_aware_utc_timestamp():
    before = datetime.now(timezone.utc)
    envelope = Envelope.create("ping")
    after = datetime.now(timezone.utc)

    assert envelope.created_at.utcoffset() == timedelta(0)
    assert before <= envelope.created_at <= after


@pytest.mark.parametrize("empty_payload", [None, {}])
def test_create_treats_missing_or_empty_payload_as_empty_dict(empty_payload):
    assert Envelope.create("ping", empty_payload).payload == {}


def test_default_payloads_are_not_shared_between_envelopes():
    first = Envelope.create("ping")
    second = Envelope.create("ping")

    # The model is frozen, but the payload dict itself is still mutable.
    first.payload["leak"] = True

    assert second.payload == {}


def test_create_rejects_empty_command():
    with pytest.raises(ValidationError):
        Envelope.create("")


# --- Model validation -------------------------------------------------------


def test_envelope_is_frozen(envelope):
    with pytest.raises(ValidationError):
        envelope.command = "other"


def test_unknown_fields_are_rejected(envelope_data):
    with pytest.raises(ValidationError):
        Envelope(**envelope_data, unexpected="value")


@pytest.mark.parametrize("field", ["message_id", "command"])
def test_empty_required_strings_are_rejected(envelope_data, field):
    envelope_data[field] = ""

    with pytest.raises(ValidationError):
        Envelope(**envelope_data)


@pytest.mark.parametrize("field", ["message_id", "command", "created_at"])
def test_required_fields_must_be_present(envelope_data, field):
    del envelope_data[field]

    with pytest.raises(ValidationError):
        Envelope(**envelope_data)


def test_naive_created_at_is_rejected(envelope_data):
    envelope_data["created_at"] = datetime(2024, 5, 17, 12, 0, 0)

    with pytest.raises(ValidationError):
        Envelope(**envelope_data)


@pytest.mark.parametrize("payload", [[1, 2], "text", 5])
def test_payload_must_be_a_mapping(envelope_data, payload):
    envelope_data["payload"] = payload

    with pytest.raises(ValidationError):
        Envelope(**envelope_data)


# --- encode -----------------------------------------------------------------


def test_encode_returns_utf8_json_bytes(envelope):
    encoded = envelope.encode()

    assert isinstance(encoded, bytes)
    assert json.loads(encoded.decode("utf-8"))["command"] == "acquire_permit"


def test_encode_contains_exactly_the_envelope_fields(envelope):
    assert set(json.loads(envelope.encode())) == {
        "message_id",
        "command",
        "payload",
        "correlation_id",
        "reply_to",
        "error",
        "created_at",
    }


def test_encode_writes_created_at_as_iso_8601(envelope):
    created_at = json.loads(envelope.encode())["created_at"]

    assert datetime.fromisoformat(created_at) == envelope.created_at


# --- decode -----------------------------------------------------------------


def test_decode_round_trips_a_full_envelope(envelope):
    assert Envelope.decode(envelope.encode()) == envelope


def test_decode_round_trips_an_error_response():
    response = Envelope.create(
        "acquire_permit_result",
        correlation_id="corr-1",
        error="RATE_LIMIT_BACKEND_UNAVAILABLE",
    )

    assert Envelope.decode(response.encode()) == response


def test_round_trip_preserves_non_ascii_payload(envelope_data):
    envelope_data["payload"] = {"text": "Привет, мир ✓"}
    original = Envelope(**envelope_data)

    decoded = Envelope.decode(original.encode())

    assert decoded.payload == {"text": "Привет, мир ✓"}


def test_round_trip_preserves_timezone_offset(envelope_data):
    plus_three = timezone(timedelta(hours=3))
    envelope_data["created_at"] = datetime(2024, 5, 17, 15, 0, tzinfo=plus_three)

    decoded = Envelope.decode(Envelope(**envelope_data).encode())

    assert decoded.created_at.utcoffset() == timedelta(hours=3)


def test_decode_accepts_z_suffix_timestamp(wire_dict, to_bytes):
    wire_dict["created_at"] = "2024-05-17T12:30:45Z"

    decoded = Envelope.decode(to_bytes(wire_dict))

    assert decoded.created_at == datetime(2024, 5, 17, 12, 30, 45, tzinfo=timezone.utc)


def test_decode_fills_optional_fields_when_absent(wire_dict, to_bytes):
    for field in ("payload", "correlation_id", "reply_to", "error"):
        del wire_dict[field]

    decoded = Envelope.decode(to_bytes(wire_dict))

    assert decoded.payload == {}
    assert decoded.correlation_id is None
    assert decoded.reply_to is None
    assert decoded.error is None


@pytest.mark.parametrize(
    "value",
    [b"", b"not json", b"\xff\xfe\x00", b"[]", b"null", b'"text"'],
)
def test_decode_rejects_malformed_or_non_object_json(value):
    with pytest.raises(ValidationError):
        Envelope.decode(value)


def test_decode_rejects_unknown_fields(wire_dict, to_bytes):
    wire_dict["unexpected"] = 1

    with pytest.raises(ValidationError):
        Envelope.decode(to_bytes(wire_dict))


@pytest.mark.parametrize("field", ["message_id", "command", "created_at"])
def test_decode_rejects_missing_required_fields(wire_dict, to_bytes, field):
    del wire_dict[field]

    with pytest.raises(ValidationError):
        Envelope.decode(to_bytes(wire_dict))


@pytest.mark.parametrize("field", ["message_id", "command"])
def test_decode_rejects_empty_required_strings(wire_dict, to_bytes, field):
    wire_dict[field] = ""

    with pytest.raises(ValidationError):
        Envelope.decode(to_bytes(wire_dict))


def test_decode_rejects_naive_timestamp(wire_dict, to_bytes):
    wire_dict["created_at"] = "2024-05-17T12:30:45"

    with pytest.raises(ValidationError):
        Envelope.decode(to_bytes(wire_dict))


def test_decode_rejects_non_object_payload(wire_dict, to_bytes):
    wire_dict["payload"] = [1, 2, 3]

    with pytest.raises(ValidationError):
        Envelope.decode(to_bytes(wire_dict))

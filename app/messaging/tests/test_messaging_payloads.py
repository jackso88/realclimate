"""Tests for Kafka message serialization helpers."""

from app.messaging.models import Envelope
from app.messaging.payloads import decode_bytes, encode_bytes


def test_envelope_round_trip_preserves_unicode_payload():
    original = Envelope.create("test", {"message": "готово"}, correlation_id="corr")
    decoded = Envelope.decode(original.encode())
    assert decoded.command == original.command
    assert decoded.payload == original.payload
    assert decoded.correlation_id == "corr"


def test_binary_payload_round_trip():
    content = b"csv\x00data\n"
    assert decode_bytes(encode_bytes(content)) == content

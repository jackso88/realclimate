"""Compact binary values for transport inside JSON Kafka envelopes."""

import base64
import gzip


def encode_bytes(content: bytes) -> str:
    """Compress and base64 encode arbitrary file content for JSON transport."""
    return base64.b64encode(gzip.compress(content)).decode("ascii")


def decode_bytes(encoded: str) -> bytes:
    """Decode a compressed binary Kafka payload."""
    return gzip.decompress(base64.b64decode(encoded))

"""Compact binary values for transport inside JSON Kafka envelopes."""

import base64
import gzip


def encode_bytes(content: bytes) -> str:
    """Compress binary content and encode it for JSON transport.

    Args:
        content: Uncompressed file or other binary content.

    Returns:
        Base64 ASCII text containing gzip-compressed content.
    """
    return base64.b64encode(gzip.compress(content)).decode("ascii")


def decode_bytes(encoded: str) -> bytes:
    """Decode and decompress a binary Kafka payload.

    Args:
        encoded: Base64 ASCII text produced by :func:`encode_bytes`.

    Returns:
        The original uncompressed byte content.

    Raises:
        ValueError: If the string is not valid base64 data.
        OSError: If the decoded bytes are not a valid gzip stream.
    """
    return gzip.decompress(base64.b64decode(encoded))

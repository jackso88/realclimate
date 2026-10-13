"""Kafka response producer for the reference spreadsheet downloader."""

from app.messaging.kafka import KafkaBus, publish_reply
from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import REFERENCE_DOWNLOAD_RESPONSES


def publish_reference_csv(bus: KafkaBus, request: Envelope, content: bytes) -> None:
    """Compress, encode, and publish reference CSV bytes as a reply.

    Args:
        bus: Kafka producer used to publish the response.
        request: Original request envelope containing its correlation ID and
            reply topic.
        content: Serialized CSV bytes read from the reference worksheet.
    """
    publish_reply(bus, request, {"csv_gzip_base64": encode_bytes(content)})


def response_topic() -> str:
    """Return the response topic used by the orchestrator."""
    return REFERENCE_DOWNLOAD_RESPONSES

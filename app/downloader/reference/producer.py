"""Kafka response producer for the reference spreadsheet downloader."""

from app.messaging.kafka import KafkaBus, publish_reply
from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import REFERENCE_DOWNLOAD_RESPONSES


def publish_reference_csv(bus: KafkaBus, request: Envelope, content: bytes) -> None:
    """Publish reference sheet bytes to the requester's reply topic."""
    publish_reply(bus, request, {"csv_gzip_base64": encode_bytes(content)})


def response_topic() -> str:
    """Return the response topic consumed by core."""
    return REFERENCE_DOWNLOAD_RESPONSES

"""Kafka request producer for processed catalogue imports."""

from app.messaging.kafka import KafkaBus
from app.messaging.payloads import encode_bytes
from app.messaging.topics import UPLOADER_REQUESTS


def request_import(
    bus: KafkaBus,
    response_topic: str,
    response_group: str,
    csv_content: bytes,
    filename: str = "processed.csv",
    timeout: float = 1200,
):
    """Send CSV bytes to uploader and await its completed import response."""
    return bus.request(
        UPLOADER_REQUESTS,
        response_topic,
        "import_processed_csv",
        {
            "filename": filename,
            "csv_gzip_base64": encode_bytes(csv_content),
        },
        timeout=timeout,
        response_group=response_group,
    )

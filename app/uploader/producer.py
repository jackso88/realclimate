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
    """Send CSV content to the uploader and wait for import completion.

    Args:
        bus: Kafka bus used to send the import request and receive its reply.
        response_topic: Topic subscribed to for this request's response.
        response_group: Consumer group used for the response subscription.
        csv_content: Processed catalogue in CSV byte form.
        filename: Filename label presented to the CMS; defaults to
            ``processed.csv``.
        timeout: Maximum wait for the uploader response, in seconds.

    Returns:
        The uploader's response envelope, including its completed queue number.

    Raises:
        RemoteServiceError: If the uploader reports that upload or import
            failed.
        RequestTimeoutError: If the uploader does not reply in time.
    """
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

"""Kafka response producer for the current catalogue downloader."""

from app.downloader.current.models import DownloadedCsv
from app.messaging.kafka import KafkaBus, publish_reply
from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import CURRENT_DOWNLOAD_RESPONSES


def publish_download(
    bus: KafkaBus, request: Envelope, downloaded: DownloadedCsv
) -> None:
    """Publish downloaded CSV content and metadata to the request's reply topic.

    Args:
        bus: Kafka producer used to publish the reply.
        request: Original request envelope, including its reply topic.
        downloaded: CSV content and metadata returned by the CMS export.
    """
    publish_reply(
        bus,
        request,
        {
            "cron_num": downloaded.cron_num,
            "filename": downloaded.filename,
            "csv_gzip_base64": encode_bytes(downloaded.content),
        },
    )


def response_topic() -> str:
    """Return the response topic used by the orchestrator."""
    return CURRENT_DOWNLOAD_RESPONSES

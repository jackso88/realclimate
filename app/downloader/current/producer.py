"""Kafka response producer for the current catalogue downloader."""

from app.downloader.current.models import DownloadedCsv
from app.messaging.kafka import KafkaBus, publish_reply
from app.messaging.models import Envelope
from app.messaging.payloads import encode_bytes
from app.messaging.topics import CURRENT_DOWNLOAD_RESPONSES


def publish_download(
    bus: KafkaBus, request: Envelope, downloaded: DownloadedCsv
) -> None:
    """Publish the downloaded CSV content without writing it to disk."""
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
    """Return the response topic consumed by core."""
    return CURRENT_DOWNLOAD_RESPONSES

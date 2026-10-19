"""Publish the current catalogue snapshot as an independent event."""

from app.contracts.models import Envelope
from app.downloader.current.models import DownloadedCsv
from app.messaging.kafka import KafkaBus
from app.messaging.payloads import encode_bytes
from app.messaging.topics import CURRENT_DOWNLOADS


def publish_current_snapshot(
    bus: KafkaBus, reference_event: Envelope, downloaded: DownloadedCsv
) -> Envelope:
    """Publish the current export, retaining the reference event correlation.

    Args:
        bus: Kafka producer used to publish the ready-to-process event.
        reference_event: Reference completion event that triggered this download.
        downloaded: Current CMS export and archive metadata.

    Returns:
        The published event envelope, useful for inspecting its correlation ID.
    """
    event = Envelope.create(
        "current_downloaded",
        {
            "current_csv_gzip_base64": encode_bytes(downloaded.content),
            "current_cron_num": downloaded.cron_num,
            "current_filename": downloaded.filename,
        },
        correlation_id=reference_event.correlation_id,
    )
    bus.publish(CURRENT_DOWNLOADS, event, key=event.correlation_id)
    return event

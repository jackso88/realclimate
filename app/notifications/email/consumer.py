"""Kafka consumer that emails detailed catalogue change reports."""

import logging
from functools import partial

from pydantic import ValidationError

from app.contracts.models import Envelope
from app.messaging.kafka import run_consumer
from app.messaging.topics import CORE_NOTIFICATIONS
from app.notifications.email.config import configure_logging, load_settings
from app.notifications.email.models import DetailedChangesPayload, EmailSettings
from app.notifications.email.sender import build_notification, send_email

logger = logging.getLogger(__name__)

DETAILED_CHANGES_COMMAND = "detailed_changes"
CONSUMER_GROUP = "email-notifications"


def handle_notification(
    message: Envelope,
    _bus,
    settings: EmailSettings,
) -> None:
    """Email a non-empty ``detailed_changes`` report and ignore everything else.

    Failure reports and any other command on the topic are meant for other
    consumers and are skipped. The envelope's correlation ID is kept in the
    email header, the email body, and every log line about the message.

    Args:
        message: Notification envelope read from the Kafka topic.
        _bus: Kafka bus supplied by the consumer callback; unused because this
            handler never replies.
        settings: SMTP and recipient settings loaded once at worker startup.

    Raises:
        EmailDeliveryError: If delivery failed for a possibly temporary reason;
            the consumer retries the record.
        EmailRejectedError: If the SMTP server permanently refused the email;
            the consumer logs it and moves on.
    """
    correlation_id = message.correlation_id
    if message.command != DETAILED_CHANGES_COMMAND:
        logger.debug(
            "Ignoring %r notification [correlation_id=%s]",
            message.command,
            correlation_id,
        )
        return
    try:
        payload = DetailedChangesPayload.model_validate(message.payload)
    except ValidationError:
        logger.warning(
            "Ignoring malformed detailed_changes payload [correlation_id=%s]",
            correlation_id,
        )
        return
    if not payload.changes:
        logger.info(
            "Ignoring empty detailed_changes report [correlation_id=%s]",
            correlation_id,
        )
        return
    send_email(build_notification(payload.changes, correlation_id), settings)


def main() -> None:
    """Run the email notification consumer until the process is stopped."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        CORE_NOTIFICATIONS,
        CONSUMER_GROUP,
        partial(handle_notification, settings=settings),
        service_name="notifications_email",
    )


if __name__ == "__main__":
    main()

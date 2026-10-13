"""Kafka consumer that forwards failures and non-empty change reports."""

import logging
import os

from app.messaging.kafka import run_consumer
from app.messaging.models import Envelope
from app.messaging.topics import CORE_NOTIFICATIONS
from app.logging_config import configure_logging
from app.notifications.telegram import send_telegram_message

logger = logging.getLogger(__name__)


def handle_notification(message: Envelope, _bus) -> None:
    """Send failures and non-empty change reports to the admin chat.

    Args:
        message: Notification envelope containing a failure or change report.
        _bus: Kafka bus supplied by the consumer callback; unused by this
            Telegram-only handler.
    """
    if message.command == "failure":
        payload = message.payload
        text = (
            f"Ошибка сервиса {payload.get('service', 'unknown')} "
            f"({payload.get('error_type', 'Error')}): {payload.get('error', '')}"
        )
    elif message.command == "detailed_changes":
        changes = message.payload.get("changes") or []
        if not changes:
            return
        text = "Изменения каталога:\n" + "\n".join(changes)
    else:
        logger.warning("Unknown notification command: %s", message.command)
        return
    send_telegram_message(text)


def main() -> None:
    """Run the Telegram notification consumer."""
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        CORE_NOTIFICATIONS,
        "telegram-notifications",
        handle_notification,
        service_name="notifications",
    )


if __name__ == "__main__":
    main()

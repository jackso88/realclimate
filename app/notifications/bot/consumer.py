"""Kafka consumer that forwards failures and non-empty change reports."""

import logging
from functools import partial

from app.messaging.kafka import run_consumer
from app.contracts.models import Envelope
from app.messaging.topics import CORE_NOTIFICATIONS
from app.notifications.bot.config import configure_logging, load_settings
from app.notifications.bot.models import NotificationSettings
from app.notifications.bot.telegram import send_telegram_message

logger = logging.getLogger(__name__)


def handle_notification(
    message: Envelope,
    _bus,
    settings: NotificationSettings | None = None,
) -> None:
    """Send failures and non-empty change reports to the admin chat.

    Args:
        message: Notification envelope containing a failure or change report.
        _bus: Kafka bus supplied by the consumer callback; unused by this
            Telegram-only handler.
        settings: Optional notification settings injected once at worker startup.
    """
    if message.command == "failure":
        payload = message.payload
        correlation = (
            f" [correlation_id={message.correlation_id}]"
            if message.correlation_id
            else ""
        )
        text = (
            f"Ошибка сервиса {payload.get('service', 'unknown')} "
            f"({payload.get('error_type', 'Error')}): {payload.get('error', '')}"
            f"{correlation}"
        )
    elif message.command == "detailed_changes":
        changes = message.payload.get("changes") or []
        if not changes:
            return
        text = "Изменения каталога:\n" + "\n".join(changes)
    else:
        logger.warning("Unknown notification command: %s", message.command)
        return
    if settings is None:
        send_telegram_message(text)
    else:
        send_telegram_message(text, settings=settings)


def main() -> None:
    """Run the Telegram notification consumer."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        CORE_NOTIFICATIONS,
        "telegram-notifications",
        partial(handle_notification, settings=settings),
        service_name="notifications_bot",
    )


if __name__ == "__main__":
    main()

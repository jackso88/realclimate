"""Telegram notification service configuration."""

import logging
import os
from app.notifications.bot.models import NotificationSettings


def load_settings() -> NotificationSettings:
    """Load the notification service's process-environment configuration.

    Returns:
        Telegram and Kafka settings. Bot credentials remain optional until a
        notification is sent, allowing the consumer to start and report config
        errors through its normal logs.
    """
    return NotificationSettings.model_validate(dict(os.environ))


def configure_logging(level: int = logging.INFO) -> None:
    """Configure this service's standard console log format.

    Args:
        level: Minimum severity to emit; defaults to ``logging.INFO``.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

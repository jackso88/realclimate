"""Telegram notification service configuration."""

import logging
import os
from pydantic import BaseModel, ConfigDict, Field, model_validator


class NotificationSettings(BaseModel):
    """Validated Telegram, Kafka, and message-format settings.

    Args:
        bot_token: Telegram Bot API token; hidden from model representations.
        chat_id: Telegram destination chat identifier.
        bootstrap_servers: Kafka broker addresses.
        api_timeout_seconds: Maximum time per Bot API request.
        telegram_message_limit: Telegram's maximum message length.
        message_part_limit: Safe character limit used when splitting reports.
        pause_between_parts_seconds: Delay between messages sent to one chat.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    bot_token: str | None = Field(
        default=None, validation_alias="TELEGRAM_BOT_TOKEN", repr=False
    )
    chat_id: str | None = Field(default=None, validation_alias="TELEGRAM_CHAT_ID")
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    api_timeout_seconds: float = Field(default=15, gt=0)
    telegram_message_limit: int = Field(default=4096, gt=0)
    message_part_limit: int = Field(default=4000, gt=0)
    pause_between_parts_seconds: float = Field(default=1.0, ge=0)

    @model_validator(mode="after")
    def part_limit_fits_telegram_limit(self) -> "NotificationSettings":
        """Ensure the safe chunk size does not exceed Telegram's hard limit."""
        if self.message_part_limit > self.telegram_message_limit:
            raise ValueError("message_part_limit cannot exceed telegram_message_limit")
        return self


def load_settings() -> NotificationSettings:
    """Load the notification service's process and dotenv configuration.

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

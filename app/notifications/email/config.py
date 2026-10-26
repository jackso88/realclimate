"""Email notification service configuration."""

import logging
import os

from app.notifications.email.models import EmailSettings


def load_settings() -> EmailSettings:
    """Load and validate the email service settings from environment variables.

    The variables are expected in the container environment; no dotenv file is
    read.

    Returns:
        Validated SMTP, recipient, and Kafka settings.

    Raises:
        pydantic.ValidationError: If a required variable is missing or a value
            is invalid, so a misconfigured container fails at startup.
    """
    return EmailSettings.model_validate(dict(os.environ))


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

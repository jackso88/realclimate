"""Environment configuration for the database worker."""

import logging
import os

from pydantic import ValidationError

from app.db_service.models import DbServiceSettings


def load_settings() -> DbServiceSettings:
    """Load and validate the database worker settings from the environment.

    Returns:
        The validated settings.

    Raises:
        ValueError: If a required variable is missing or invalid. The message
            lists the offending variables without echoing any values, because
            the environment holds credentials.
    """
    try:
        return DbServiceSettings.model_validate(dict(os.environ))
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise ValueError(f"Invalid database service settings: {problems}") from error


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the database worker's console logging.

    Args:
        level: Minimum severity to emit; defaults to ``logging.INFO``.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

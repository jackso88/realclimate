"""Pydantic-backed settings for the core catalogue processing worker."""

import logging
import os

from pydantic import ValidationError

from app.core.models import CoreSettings


def load_settings() -> CoreSettings:
    """Read and validate the core worker's Kafka and output-file settings.

    Returns:
        A validated core runtime configuration.

    Raises:
        ValueError: If a setting has an invalid value.
    """
    try:
        return CoreSettings.model_validate(dict(os.environ))
    except ValidationError as error:
        raise ValueError(f"Invalid core settings: {error}") from error


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

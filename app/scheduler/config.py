"""Pydantic-backed scheduler configuration and logging setup."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.scheduler.models import SchedulerSettings


def load_settings(env_file: str | Path | None = None) -> SchedulerSettings:
    """Load and validate scheduler settings from the process or dotenv file.

    Args:
        env_file: Optional dotenv path. When omitted, only process environment
            variables are read.

    Returns:
        Validated scheduling and Kafka settings.

    Raises:
        ValueError: If the timezone or RPC timeout is invalid.
    """
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
    try:
        return SchedulerSettings.model_validate(dict(os.environ))
    except ValidationError as error:
        raise ValueError(f"Invalid scheduler settings: {error}") from error


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

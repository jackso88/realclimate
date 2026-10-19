"""Pydantic-backed scheduler configuration and logging setup."""

import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class SchedulerSettings(BaseModel):
    """Validated timezone, Kafka, and RPC timeout settings for the scheduler.

    Args:
        timezone: IANA timezone used for the weekday schedule.
        bootstrap_servers: Kafka broker addresses.
        orchestrator_timeout_seconds: Maximum wait for one workflow RPC.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    timezone: str = Field(default="Europe/Minsk", validation_alias="SCHEDULE_TIMEZONE")
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    orchestrator_timeout_seconds: float = Field(
        default=5400,
        validation_alias="ORCHESTRATOR_RUN_TIMEOUT_SECONDS",
        gt=0,
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require a known IANA timezone name."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown schedule timezone: {value}") from error
        return value


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

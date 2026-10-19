"""Pydantic-backed settings for the core catalogue processing worker."""

import logging
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CoreSettings(BaseModel):
    """Validated storage and Kafka settings for the core service.

    Args:
        bootstrap_servers: Kafka broker addresses.
        excluded_csv_path: Path where the manual-review CSV is persisted.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
        min_length=1,
    )
    excluded_csv_path: Path = Field(
        default=Path("/app/storage/outputs/for_zalivka_excluded.csv"),
        validation_alias="EXCLUDED_CSV_PATH",
    )


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

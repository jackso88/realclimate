"""Pydantic-backed environment configuration for the uploader."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.uploader.exceptions import UploaderConfigurationError
from app.uploader.models import Settings


class UploaderEnvironment(BaseModel):
    """Validated environment values consumed by the uploader service.

    Args:
        cms_url: HTTP or HTTPS CMS API base URL.
        shop_id: Positive CMS shop identifier.
        ver_id: Positive CMS version identifier.
        access: CMS access parameter, preserved without URL decoding.
        bootstrap_servers: Kafka broker addresses for this worker.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    cms_url: str = Field(validation_alias="TAPTOP_CMS_URL", min_length=1)
    shop_id: int = Field(validation_alias="TAPTOP_SHOP_ID", gt=0)
    ver_id: int = Field(validation_alias="TAPTOP_VER_ID", gt=0)
    access: str = Field(validation_alias="TAPTOP_ACCESS", min_length=1)
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load, validate, and convert the uploader's CMS and Kafka settings.

    Args:
        env_file: Optional dotenv file. Otherwise the repository-root ``.env``
            is loaded when present; process environment values take precedence.

    Returns:
        Validated settings needed to upload and import CSV data.

    Raises:
        UploaderConfigurationError: If required values are missing or invalid.
    """
    if env_file is None:
        env_file = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=env_file, override=False)

    values = dict(os.environ)
    required = ("TAPTOP_CMS_URL", "TAPTOP_SHOP_ID", "TAPTOP_VER_ID", "TAPTOP_ACCESS")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise UploaderConfigurationError(
            f"Missing required environment setting(s): {', '.join(missing)}"
        )

    try:
        config = UploaderEnvironment.model_validate(values)
        return Settings(
            cms_url=config.cms_url,
            shop_id=config.shop_id,
            ver_id=config.ver_id,
            access=config.access,
            bootstrap_servers=config.bootstrap_servers,
        )
    except ValidationError as error:
        fields = {str(item["loc"][0]) for item in error.errors()}
        if fields.intersection({"TAPTOP_CMS_URL", "cms_url"}):
            raise UploaderConfigurationError(
                "TAPTOP_CMS_URL must start with http:// or https://"
            ) from error
        if fields.intersection({"TAPTOP_SHOP_ID", "TAPTOP_VER_ID"}):
            if any(
                item["type"] == "int_parsing"
                for item in error.errors()
                if item["loc"][0] in {"TAPTOP_SHOP_ID", "TAPTOP_VER_ID"}
            ):
                raise UploaderConfigurationError(
                    "TAPTOP_SHOP_ID and TAPTOP_VER_ID must be integers"
                ) from error
            raise UploaderConfigurationError(
                "TAPTOP_SHOP_ID and TAPTOP_VER_ID must be positive integers"
            ) from error
        raise UploaderConfigurationError(
            f"Invalid uploader settings: {error}"
        ) from error


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

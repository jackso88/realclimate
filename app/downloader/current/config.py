"""Pydantic-backed configuration for the current catalogue downloader."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.downloader.current.models import CurrentDownloaderConfig

from app.downloader.current.exceptions import ConfigurationError
from app.downloader.current.models import Settings


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load, validate, and convert downloader environment settings.

    Args:
        env_file: Optional dotenv file. When omitted, the repository-root
            ``.env`` is loaded if present; process variables take precedence.

    Returns:
        Validated CMS and Kafka settings for the downloader.

    Raises:
        ConfigurationError: If required values are missing, URLs are invalid,
            or identifiers fail validation.
    """
    if env_file is None:
        env_file = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(dotenv_path=env_file, override=False)

    values = dict(os.environ)
    required = ("TAPTOP_CMS_URL", "TAPTOP_SHOP_ID", "TAPTOP_VER_ID", "TAPTOP_ACCESS")
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise ConfigurationError(
            f"Missing required environment setting(s): {', '.join(missing)}"
        )

    try:
        config = CurrentDownloaderConfig.model_validate(values)
        return Settings(
            cms_url=config.cms_url,
            shop_id=config.shop_id,
            ver_id=config.ver_id,
            access=config.access,
            bootstrap_servers=config.bootstrap_servers,
        )
    except ValidationError as error:
        fields = {str(item["loc"][0]) for item in error.errors()}
        for name in ("TAPTOP_SHOP_ID", "TAPTOP_VER_ID"):
            if name in fields:
                raise ConfigurationError(f"{name} must be an integer") from error
        if fields.intersection({"TAPTOP_CMS_URL", "cms_url"}):
            raise ConfigurationError(
                "TAPTOP_CMS_URL must start with http:// or https://"
            ) from error
        raise ConfigurationError(f"Invalid downloader settings: {error}") from error


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

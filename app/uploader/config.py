"""Configuration for the uploader worker."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from app.uploader.exceptions import UploaderConfigurationError
from app.uploader.models import Settings


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load and validate CMS settings required by the uploader.

    Args:
        env_file: Optional environment file. When omitted, the project-root
            ``.env`` is loaded if present; process environment values take
            precedence.

    Returns:
        Immutable CMS settings for upload and product import requests.

    Raises:
        UploaderConfigurationError: If a required value is missing, the CMS
            URL is invalid, or an integer setting cannot be parsed.
    """
    if env_file is None:
        env_file = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(dotenv_path=env_file, override=False)

    required = ("TAPTOP_CMS_URL", "TAPTOP_SHOP_ID", "TAPTOP_VER_ID", "TAPTOP_ACCESS")
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise UploaderConfigurationError(
            f"Missing required environment setting(s): {', '.join(missing)}"
        )

    cms_url = os.environ["TAPTOP_CMS_URL"].rstrip("/")
    if not cms_url.startswith(("http://", "https://")):
        raise UploaderConfigurationError(
            "TAPTOP_CMS_URL must start with http:// or https://"
        )

    try:
        shop_id = int(os.environ["TAPTOP_SHOP_ID"])
        ver_id = int(os.environ["TAPTOP_VER_ID"])
    except ValueError as error:
        raise UploaderConfigurationError(
            "TAPTOP_SHOP_ID and TAPTOP_VER_ID must be integers"
        ) from error

    return Settings(
        cms_url=cms_url,
        shop_id=shop_id,
        ver_id=ver_id,
        access=os.environ["TAPTOP_ACCESS"],
    )


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

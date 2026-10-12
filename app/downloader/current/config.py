"""Configuration for the current catalogue downloader."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.downloader.current.exceptions import ConfigurationError
from app.downloader.current.models import Settings


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load the CMS shop settings needed to request and fetch an export."""
    if env_file is None:
        env_file = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(dotenv_path=env_file, override=False)

    required = ("TAPTOP_CMS_URL", "TAPTOP_SHOP_ID", "TAPTOP_VER_ID", "TAPTOP_ACCESS")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ConfigurationError(
            f"Missing required environment setting(s): {', '.join(missing)}"
        )

    cms_url = os.environ["TAPTOP_CMS_URL"].rstrip("/")
    if not cms_url.startswith(("https://", "http://")):
        raise ConfigurationError("TAPTOP_CMS_URL must start with http:// or https://")

    return Settings(
        cms_url=cms_url,
        shop_id=_required_integer("TAPTOP_SHOP_ID"),
        ver_id=_required_integer("TAPTOP_VER_ID"),
        access=os.environ["TAPTOP_ACCESS"],
    )


def _required_integer(name: str) -> int:
    """Read an integer setting and report invalid values clearly."""
    try:
        return int(os.environ[name])
    except ValueError as error:
        raise ConfigurationError(f"{name} must be an integer") from error

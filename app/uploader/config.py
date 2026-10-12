"""Load and validate uploader settings from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.uploader.exceptions import UploaderConfigurationError
from app.uploader.models import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROCESSED_FILE = PROJECT_ROOT / "storage" / "outputs" / "processed.csv"


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load uploader settings using the same required credentials as downloader.

    Args:
        env_file: Optional dotenv path. Defaults to the project root ``.env``.

    Raises:
        UploaderConfigurationError: If required variables are missing or IDs
            are not integers.
    """
    if env_file is None:
        env_file = PROJECT_ROOT / ".env"
    load_dotenv(dotenv_path=env_file, override=False)

    required = (
        "TAPTOP_DESIGN_ID",
        "TAPTOP_BASE_URL",
        "TAPTOP_USERNAME",
        "TAPTOP_PASSWORD",
        "TAPTOP_CMS_URL",
        "TAPTOP_SHOP_ID",
        "TAPTOP_VER_ID",
        "TAPTOP_ACCESS",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise UploaderConfigurationError(
            f"Missing required environment setting(s): {', '.join(missing)}"
        )

    base_url = os.environ["TAPTOP_BASE_URL"].rstrip("/")
    cms_url = os.environ["TAPTOP_CMS_URL"].rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise UploaderConfigurationError(
            "TAPTOP_BASE_URL must start with http:// or https://"
        )

    return Settings(
        ver_id=_required_integer("TAPTOP_VER_ID"),
        access=os.environ["TAPTOP_ACCESS"],
        shop_id=_required_integer("TAPTOP_SHOP_ID"),
        cms_url=cms_url,
        base_url=base_url,
        username=os.environ["TAPTOP_USERNAME"],
        password=os.environ["TAPTOP_PASSWORD"],
        design_id=_required_integer("TAPTOP_DESIGN_ID"),
        processed_file=Path(
            os.getenv("TAPTOP_PROCESSED_FILE", str(DEFAULT_PROCESSED_FILE))
        ),
        login_path=os.getenv("TAPTOP_LOGIN_PATH", "/login"),
        mosaic_path=os.getenv("TAPTOP_MOSAIC_PATH", "/mosaic"),
        form_name=os.getenv("TAPTOP_FORM_NAME", "login_form"),
        username_field=os.getenv("TAPTOP_USERNAME_FIELD", "email"),
        password_field=os.getenv("TAPTOP_PASSWORD_FIELD", "password"),
    )


def _required_integer(name: str) -> int:
    """Read one required integer environment variable."""
    try:
        return int(os.environ[name])
    except ValueError as error:
        raise UploaderConfigurationError(f"{name} must be an integer") from error

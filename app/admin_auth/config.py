"""Environment configuration for the admin authentication service."""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings


def load_settings(env_file: str | Path | None = None) -> AdminSettings:
    """Load CMS login settings from the project ``.env`` file."""
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(env_file or project_root / ".env", override=False)
    required = (
        "TAPTOP_BASE_URL",
        "TAPTOP_CMS_URL",
        "TAPTOP_USERNAME",
        "TAPTOP_PASSWORD",
        "TAPTOP_ACCESS",
        "TAPTOP_VER_ID",
        "TAPTOP_DESIGN_ID",
    )
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise AdminLoginError(f"Missing required settings: {', '.join(missing)}")

    try:
        ver_id = int(os.environ["TAPTOP_VER_ID"])
        design_id = int(os.environ["TAPTOP_DESIGN_ID"])
    except ValueError as error:
        raise AdminLoginError(
            "TAPTOP_VER_ID and TAPTOP_DESIGN_ID must be integers"
        ) from error

    return AdminSettings(
        base_url=os.environ["TAPTOP_BASE_URL"].rstrip("/"),
        cms_url=os.environ["TAPTOP_CMS_URL"].rstrip("/"),
        username=os.environ["TAPTOP_USERNAME"],
        password=os.environ["TAPTOP_PASSWORD"],
        access=os.environ["TAPTOP_ACCESS"],
        ver_id=ver_id,
        design_id=design_id,
        login_path=os.getenv("TAPTOP_LOGIN_PATH", "/login"),
        mosaic_path=os.getenv("TAPTOP_MOSAIC_PATH", "/mosaic"),
        form_name=os.getenv("TAPTOP_FORM_NAME", "login_form"),
        username_field=os.getenv("TAPTOP_USERNAME_FIELD", "email"),
        password_field=os.getenv("TAPTOP_PASSWORD_FIELD", "password"),
    )

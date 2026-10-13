"""Environment configuration for the admin authentication service."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings


def _positive_int(variable: str, default: int) -> int:
    """Read a positive integer setting with a default value.

    Args:
        variable: Environment variable to read.
        default: Value used when the variable is not configured.

    Returns:
        The parsed positive integer.

    Raises:
        AdminLoginError: If the value is not a positive integer.
    """
    raw_value = os.getenv(variable)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise AdminLoginError(f"{variable} must be a positive integer") from error
    if value <= 0:
        raise AdminLoginError(f"{variable} must be a positive integer")
    return value


def load_settings(env_file: str | Path | None = None) -> AdminSettings:
    """Load and validate the settings required by admin authentication.

    ``ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS`` controls how long the service
    reuses a serialized authenticated session; it defaults to 14400 seconds
    (4 hours).

    Args:
        env_file: Optional path to an environment file. When omitted, the
            project-root ``.env`` is loaded if present; existing environment
            variables take precedence.

    Returns:
        Immutable authentication settings for one worker process.

    Raises:
        AdminLoginError: If required values are missing or numeric IDs invalid.
    """
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
        session_cache_ttl_seconds=_positive_int(
            "ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS", 14400
        ),
        login_path=os.getenv("TAPTOP_LOGIN_PATH", "/login"),
        mosaic_path=os.getenv("TAPTOP_MOSAIC_PATH", "/mosaic"),
        form_name=os.getenv("TAPTOP_FORM_NAME", "login_form"),
        username_field=os.getenv("TAPTOP_USERNAME_FIELD", "email"),
        password_field=os.getenv("TAPTOP_PASSWORD_FIELD", "password"),
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

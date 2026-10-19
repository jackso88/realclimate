"""Environment configuration for the admin authentication service."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from app.admin_auth.models import AdminEnvironment

from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings


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
    environment = dict(os.environ)
    missing = [key for key in required if not environment.get(key)]
    if missing:
        raise AdminLoginError(f"Missing required settings: {', '.join(missing)}")

    try:
        config = AdminEnvironment.model_validate(environment)
        return AdminSettings(
            base_url=config.base_url,
            cms_url=config.cms_url,
            username=config.username,
            password=config.password,
            access=config.access,
            ver_id=config.ver_id,
            design_id=config.design_id,
            session_cache_ttl_seconds=config.session_cache_ttl_seconds,
            login_path=config.login_path,
            mosaic_path=config.mosaic_path,
            form_name=config.form_name,
            username_field=config.username_field,
            password_field=config.password_field,
            bootstrap_servers=config.bootstrap_servers,
        )
    except ValidationError as error:
        fields = {str(item["loc"][0]) for item in error.errors()}
        if fields.intersection({"TAPTOP_VER_ID", "TAPTOP_DESIGN_ID"}):
            is_parse_error = any(
                item["type"] == "int_parsing"
                and item["loc"][0] in {"TAPTOP_VER_ID", "TAPTOP_DESIGN_ID"}
                for item in error.errors()
            )
            if is_parse_error:
                raise AdminLoginError(
                    "TAPTOP_VER_ID and TAPTOP_DESIGN_ID must be integers"
                ) from error
            raise AdminLoginError(
                "TAPTOP_VER_ID and TAPTOP_DESIGN_ID must be positive integers"
            ) from error
        if "ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS" in fields:
            raise AdminLoginError(
                "ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS must be a positive integer"
            ) from error
        if fields.intersection({"base_url", "cms_url"}):
            raise AdminLoginError(
                "TAPTOP_BASE_URL and TAPTOP_CMS_URL must be absolute HTTP or HTTPS URLs"
            ) from error
        raise AdminLoginError(f"Invalid admin auth settings: {error}") from error


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

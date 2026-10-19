"""Environment configuration for the admin authentication service."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings


class AdminEnvironment(BaseModel):
    """Validated environment values consumed by the admin-auth service.

    Args:
        base_url: Public admin site origin.
        cms_url: CMS API origin and base path.
        username: Admin account name.
        password: Admin account password, hidden from representations.
        access: CMS access parameter.
        ver_id: Positive CMS version ID.
        design_id: Positive CMS design ID.
        session_cache_ttl_seconds: Positive auth-session cache lifetime.
        login_path: Login endpoint path.
        mosaic_path: Post-login CMS path.
        form_name: Login form identifier.
        username_field: Username input name.
        password_field: Password input name.
        bootstrap_servers: Kafka brokers for this worker.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    base_url: str = Field(validation_alias="TAPTOP_BASE_URL", min_length=1)
    cms_url: str = Field(validation_alias="TAPTOP_CMS_URL", min_length=1)
    username: str = Field(validation_alias="TAPTOP_USERNAME", min_length=1)
    password: str = Field(validation_alias="TAPTOP_PASSWORD", min_length=1, repr=False)
    access: str = Field(validation_alias="TAPTOP_ACCESS", min_length=1)
    ver_id: int = Field(validation_alias="TAPTOP_VER_ID", gt=0)
    design_id: int = Field(validation_alias="TAPTOP_DESIGN_ID", gt=0)
    session_cache_ttl_seconds: int = Field(
        default=14400, validation_alias="ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS", gt=0
    )
    login_path: str = Field(default="/login", validation_alias="TAPTOP_LOGIN_PATH")
    mosaic_path: str = Field(default="/mosaic", validation_alias="TAPTOP_MOSAIC_PATH")
    form_name: str = Field(default="login_form", validation_alias="TAPTOP_FORM_NAME")
    username_field: str = Field(
        default="email", validation_alias="TAPTOP_USERNAME_FIELD"
    )
    password_field: str = Field(
        default="password", validation_alias="TAPTOP_PASSWORD_FIELD"
    )
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )


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

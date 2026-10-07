"""Load application settings from environment variables and an optional .env file."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    """Configuration required to authenticate with the admin site.

    Attributes:
        base_url: Root URL of the admin site, without a trailing slash.
        username: Account name used by the login form.
        password: Account password used by the login form.
        login_path: Path that starts the login flow.
        username_field: HTML form field name for the account email or username.
        password_field: HTML form field name for the password.
        form_name: Value sent in the login form's ``_form`` field.
    """

    base_url: str
    username: str
    password: str
    login_path: str = "/login"
    form_name: str = "login_form"
    username_field: str = "email"
    password_field: str = "password"


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load and validate settings, preferring process environment variables.

    Args:
        env_file: Path to the dotenv file. Existing process variables take
            precedence over values in this file.

    Returns:
        Validated settings for the admin client.

    Raises:
        ValueError: If a required setting is missing or the base URL is invalid.
    """
    if env_file is None:
        # Project root is four levels above this package module.
        env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"

    load_dotenv(dotenv_path=env_file, override=False)

    required = ("TAPTOP_BASE_URL", "TAPTOP_USERNAME", "TAPTOP_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise ValueError(
            f"Missing required environment setting(s): {', '.join(missing)}"
        )

    base_url = os.environ["TAPTOP_BASE_URL"].rstrip("/")
    if not base_url.startswith(("https://", "http://")):
        raise ValueError("TAPTOP_BASE_URL must start with http:// or https://")

    return Settings(
        base_url=base_url,
        username=os.environ["TAPTOP_USERNAME"],
        password=os.environ["TAPTOP_PASSWORD"],
        login_path=os.getenv("TAPTOP_LOGIN_PATH", "/login"),
        username_field=os.getenv("TAPTOP_USERNAME_FIELD", "email"),
        password_field=os.getenv("TAPTOP_PASSWORD_FIELD", "password"),
        form_name=os.getenv("TAPTOP_FORM_NAME", "login_form"),
    )

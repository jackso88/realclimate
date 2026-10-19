"""Environment configuration for the rate-limiter worker."""

import logging
import os

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.rate_limiter.models import RateLimiterSettings


class RateLimiterEnvironment(BaseModel):
    """Environment variables consumed by the rate-limiter process."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0", validation_alias="RATE_LIMITER_REDIS_URL"
    )
    cms_min_interval_ms: int = Field(
        default=5500, validation_alias="RATE_LIMIT_CMS_MIN_INTERVAL_MS", ge=1
    )
    google_sheets_min_interval_ms: int = Field(
        default=1112, validation_alias="RATE_LIMIT_GOOGLE_SHEETS_MIN_INTERVAL_MS", ge=1
    )
    telegram_admin_chat_min_interval_ms: int = Field(
        default=3334, validation_alias="RATE_LIMIT_TELEGRAM_CHAT_MIN_INTERVAL_MS", ge=1
    )


def load_settings() -> RateLimiterSettings:
    """Load and validate rate-limiter settings from the process environment."""
    try:
        environment = RateLimiterEnvironment.model_validate(dict(os.environ))
    except ValidationError as error:
        raise ValueError(f"Invalid rate-limiter settings: {error}") from error
    return RateLimiterSettings(
        bootstrap_servers=environment.bootstrap_servers,
        redis_url=environment.redis_url,
        cms_min_interval_ms=environment.cms_min_interval_ms,
        google_sheets_min_interval_ms=environment.google_sheets_min_interval_ms,
        telegram_admin_chat_min_interval_ms=(
            environment.telegram_admin_chat_min_interval_ms
        ),
    )


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the rate-limiter's console logging.

    Args:
        level: Minimum severity to emit; defaults to ``logging.INFO``.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

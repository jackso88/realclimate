"""Validated settings and permit results for the rate-limiter service."""

from pydantic import BaseModel, ConfigDict, Field


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


class RateLimiterSettings(BaseModel):
    """Runtime broker, Redis, and per-provider spacing settings.

    Args:
        bootstrap_servers: Kafka brokers used by the rate-limiter worker.
        redis_url: Redis database holding the last permit time per bucket.
        cms_min_interval_ms: Minimum gap between all requests to the CMS
            account, including login, export, import, and polling calls.
        google_sheets_min_interval_ms: Minimum gap between Sheets API calls.
            The value is below the documented per-user quota with a 10% margin.
        telegram_admin_chat_min_interval_ms: Minimum gap between bot messages
            to the administrator group, below the documented group limit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bootstrap_servers: str = Field(min_length=1)
    redis_url: str = Field(min_length=1)
    cms_min_interval_ms: int = Field(default=5500, ge=1)
    google_sheets_min_interval_ms: int = Field(default=1112, ge=1)
    telegram_admin_chat_min_interval_ms: int = Field(default=3334, ge=1)

    def interval_for(self, bucket: str) -> int:
        """Return the configured minimum gap for a known quota bucket.

        Args:
            bucket: Stable bucket identifier requested by an application.

        Returns:
            Minimum spacing in milliseconds.

        Raises:
            KeyError: If the caller requests an unconfigured bucket.
        """
        intervals = {
            "cms:account": self.cms_min_interval_ms,
            "google:sheets": self.google_sheets_min_interval_ms,
            "telegram:admin_chat": self.telegram_admin_chat_min_interval_ms,
        }
        try:
            return intervals[bucket]
        except KeyError as error:
            raise KeyError(f"Unknown rate-limit bucket: {bucket}") from error


class PermitDecision(BaseModel):
    """The rate-limiter decision returned for one permit request.

    Args:
        granted: Whether the caller may issue its external request now.
        retry_after_ms: Delay before another permit can be acquired when
            ``granted`` is false.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    granted: bool
    retry_after_ms: int = Field(default=0, ge=0)

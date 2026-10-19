"""Validated data models for this service."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


class SchedulerSettings(BaseModel):
    """Validated timezone, Kafka, and RPC timeout settings for the scheduler.

    Args:
        timezone: IANA timezone used for the weekday schedule.
        bootstrap_servers: Kafka broker addresses.
        orchestrator_timeout_seconds: Maximum wait for one workflow RPC.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    timezone: str = Field(default="Europe/Minsk", validation_alias="SCHEDULE_TIMEZONE")
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    orchestrator_timeout_seconds: float = Field(
        default=5400,
        validation_alias="ORCHESTRATOR_RUN_TIMEOUT_SECONDS",
        gt=0,
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        """Require a known IANA timezone name."""
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown schedule timezone: {value}") from error
        return value

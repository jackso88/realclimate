"""Validated data models for this service."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class SchedulerSettings(BaseModel):
    """Validated timezone and Kafka settings for the scheduler.

    Args:
        timezone: IANA timezone used for the weekday schedule.
        bootstrap_servers: Kafka broker addresses.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    timezone: str = Field(default="Europe/Minsk", validation_alias="SCHEDULE_TIMEZONE")
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
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

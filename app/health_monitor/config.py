"""Pydantic-backed environment configuration for the health monitor."""

import logging
import os
from typing import ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)

from app.health_monitor.models import HealthMonitorSettings


class HealthMonitorEnvironment(BaseModel):
    """Validated environment settings used by the heartbeat monitor.

    Args:
        bootstrap_servers: Kafka broker addresses.
        monitored_services: Worker names expected to emit heartbeats.
        heartbeat_timeout_seconds: Maximum allowed age of a heartbeat.
        startup_grace_seconds: Grace period before missing-heartbeat alerts.
        check_interval_seconds: Interval between health and broker checks.
        max_busy_seconds: Global maximum duration for one worker operation.
        busy_limit_overrides: Per-service replacement limits in seconds.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    DEFAULT_MONITORED_SERVICES: ClassVar[tuple[str, ...]] = (
        "admin_auth",
        "downloader_current",
        "downloader_reference",
        "core",
        "orchestrator",
        "uploader",
        "scheduler",
        "notifications",
    )

    bootstrap_servers: str = Field(
        default="localhost:9092",
        validation_alias="KAFKA_BOOTSTRAP_SERVERS",
        min_length=1,
    )
    monitored_services: tuple[str, ...] = Field(
        default=DEFAULT_MONITORED_SERVICES,
        validation_alias="HEALTH_MONITORED_SERVICES",
        min_length=1,
    )
    heartbeat_timeout_seconds: PositiveInt = Field(
        default=120, validation_alias="HEALTH_HEARTBEAT_TIMEOUT_SECONDS"
    )
    startup_grace_seconds: PositiveInt = Field(
        default=180, validation_alias="HEALTH_STARTUP_GRACE_SECONDS"
    )
    check_interval_seconds: PositiveInt = Field(
        default=10, validation_alias="HEALTH_CHECK_INTERVAL_SECONDS"
    )
    max_busy_seconds: PositiveInt = Field(
        default=5400, validation_alias="HEALTH_MAX_BUSY_SECONDS"
    )
    busy_limit_overrides: dict[str, PositiveInt] = Field(
        default_factory=dict, validation_alias="HEALTH_MAX_BUSY_OVERRIDES"
    )

    @field_validator("monitored_services", mode="before")
    @classmethod
    def parse_monitored_services(cls, value: object) -> tuple[str, ...]:
        """Normalize the comma-separated worker list and remove duplicates."""
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (tuple, list)):
            raise ValueError("HEALTH_MONITORED_SERVICES must be a list of names")
        services = tuple(dict.fromkeys(item.strip() for item in value if item.strip()))
        if not services:
            raise ValueError("HEALTH_MONITORED_SERVICES must name at least one service")
        return services

    @field_validator("busy_limit_overrides", mode="before")
    @classmethod
    def parse_busy_overrides(cls, value: object) -> dict[str, int]:
        """Parse comma-separated ``service=seconds`` overrides."""
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            raise ValueError("HEALTH_MAX_BUSY_OVERRIDES must be service=seconds pairs")
        overrides: dict[str, int] = {}
        for entry in (part.strip() for part in value.split(",") if part.strip()):
            name, separator, seconds = entry.partition("=")
            try:
                limit = int(seconds)
            except ValueError:
                limit = 0
            if not separator or not name.strip() or limit <= 0:
                raise ValueError(
                    "HEALTH_MAX_BUSY_OVERRIDES entries must look like "
                    f"service=seconds with positive seconds, got {entry!r}"
                )
            overrides[name.strip()] = limit
        return overrides

    @model_validator(mode="after")
    def overrides_are_monitored(self) -> "HealthMonitorEnvironment":
        """Reject override names that do not correspond to monitored workers."""
        for name in self.busy_limit_overrides:
            if name not in self.monitored_services:
                raise ValueError(
                    f"HEALTH_MAX_BUSY_OVERRIDES names unknown service {name!r}"
                )
        return self


def load_settings() -> HealthMonitorSettings:
    """Load, validate, and convert health-monitor settings.

    Returns:
        Validated heartbeat, Kafka, and stuck-worker thresholds.

    Raises:
        ValueError: If a duration, service name, or per-service override is invalid.
    """
    try:
        config = HealthMonitorEnvironment.model_validate(dict(os.environ))
    except ValidationError as error:
        raise ValueError(str(error)) from error
    return HealthMonitorSettings(
        bootstrap_servers=config.bootstrap_servers,
        monitored_services=config.monitored_services,
        heartbeat_timeout_seconds=config.heartbeat_timeout_seconds,
        startup_grace_seconds=config.startup_grace_seconds,
        check_interval_seconds=config.check_interval_seconds,
        max_busy_seconds=config.max_busy_seconds,
        busy_limit_overrides=config.busy_limit_overrides,
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

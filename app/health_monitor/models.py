"""Data transfer objects for health monitoring."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)
from typing import ClassVar

AVAILABILITY = "availability"
STUCK = "stuck"


class HealthMonitorSettings(BaseModel):
    """Runtime settings for heartbeat and Kafka availability monitoring.

    Args:
        bootstrap_servers: Comma-separated Kafka broker addresses.
        monitored_services: Stable heartbeat names expected from workers.
        heartbeat_timeout_seconds: Maximum age of a heartbeat before a worker
            is marked unavailable.
        startup_grace_seconds: Delay before missing first heartbeats are alerts.
        check_interval_seconds: Delay between monitor polling and broker checks.
        max_busy_seconds: Longest a worker may spend on one message before it
            is reported as stuck. A worker that still sends heartbeats but
            never finishes a message is alive, yet not doing its job.
        busy_limit_overrides: Per-service replacements for ``max_busy_seconds``,
            for example a short limit for a service that should answer fast.
        max_busy_seconds: Positive upper bound for one worker operation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    busy_limit_overrides: dict[str, PositiveInt] = Field(default_factory=dict)
    monitored_services: tuple[str, ...] = Field(min_length=1)
    heartbeat_timeout_seconds: int = Field(default=120, gt=0)
    startup_grace_seconds: int = Field(default=180, gt=0)
    check_interval_seconds: int = Field(default=10, gt=0)
    max_busy_seconds: int = Field(default=5400, gt=0)
    bootstrap_servers: str = Field(min_length=1)


class ServiceTransition(BaseModel):
    """A change in a worker's health that deserves an alert.

    Args:
        service: Stable service name from the heartbeat payload.
        available: True for a recovery and False for a problem.
        kind: ``"availability"`` when heartbeats stopped or resumed, or
            ``"stuck"`` when the worker is alive but has been busy with one
            message for too long (or has finished it).
        busy_seconds: For ``"stuck"``, how long the message has been in
            progress.
        limit_seconds: For ``"stuck"``, the limit that was exceeded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["availability", "stuck"] = AVAILABILITY
    busy_seconds: float = Field(default=0.0, ge=0)
    limit_seconds: int = Field(default=0, ge=0)
    service: str = Field(min_length=1)
    available: bool


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
        "core",
        "uploader",
        "scheduler",
        "admin_auth",
        "rate_limiter",
        "notifications_bot",
        "notifications_email",
        "downloader_current",
        "downloader_reference",
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

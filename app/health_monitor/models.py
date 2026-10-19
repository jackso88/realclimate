"""Data transfer objects for health monitoring."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


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

    bootstrap_servers: str = Field(min_length=1)
    monitored_services: tuple[str, ...] = Field(min_length=1)
    heartbeat_timeout_seconds: int = Field(default=120, gt=0)
    startup_grace_seconds: int = Field(default=180, gt=0)
    check_interval_seconds: int = Field(default=10, gt=0)
    max_busy_seconds: int = Field(default=5400, gt=0)
    busy_limit_overrides: dict[str, PositiveInt] = Field(default_factory=dict)


AVAILABILITY = "availability"
STUCK = "stuck"


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

    service: str = Field(min_length=1)
    available: bool
    kind: Literal["availability", "stuck"] = AVAILABILITY
    busy_seconds: float = Field(default=0.0, ge=0)
    limit_seconds: int = Field(default=0, ge=0)

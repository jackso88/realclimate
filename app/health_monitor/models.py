"""Data transfer objects for health monitoring."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class HealthMonitorSettings:
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
    """

    bootstrap_servers: str
    monitored_services: tuple[str, ...]
    heartbeat_timeout_seconds: int = 120
    startup_grace_seconds: int = 180
    check_interval_seconds: int = 10
    max_busy_seconds: int = 5400
    busy_limit_overrides: dict[str, int] = field(default_factory=dict)


AVAILABILITY = "availability"
STUCK = "stuck"


@dataclass(frozen=True)
class ServiceTransition:
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

    service: str
    available: bool
    kind: str = AVAILABILITY
    busy_seconds: float = 0.0
    limit_seconds: int = 0

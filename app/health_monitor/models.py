"""Data transfer objects for health monitoring."""

from dataclasses import dataclass


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
    """

    bootstrap_servers: str
    monitored_services: tuple[str, ...]
    heartbeat_timeout_seconds: int = 120
    startup_grace_seconds: int = 180
    check_interval_seconds: int = 10


@dataclass(frozen=True)
class ServiceTransition:
    """A worker's transition into or out of the unavailable state.

    Args:
        service: Stable service name from the heartbeat payload.
        available: True for a recovery and False for an outage.
    """

    service: str
    available: bool

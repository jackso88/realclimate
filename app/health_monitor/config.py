"""Environment-based configuration for the health monitor."""

import logging
import os

from app.health_monitor.models import HealthMonitorSettings

DEFAULT_MONITORED_SERVICES = (
    "admin_auth",
    "downloader_current",
    "downloader_reference",
    "core",
    "orchestrator",
    "uploader",
    "scheduler",
    "notifications",
)


def _positive_int(variable: str, default: int) -> int:
    """Read a positive integer environment variable.

    Args:
        variable: Environment variable name.
        default: Value used when the variable is unset.

    Returns:
        The configured positive integer.

    Raises:
        ValueError: If the configured value is not a positive integer.
    """
    raw_value = os.getenv(variable)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{variable} must be a positive integer")
    return value


def _busy_overrides(monitored_services: tuple[str, ...]) -> dict[str, int]:
    """Parse per-service busy limits from ``HEALTH_MAX_BUSY_OVERRIDES``.

    Args:
        monitored_services: Services that heartbeat names may refer to.

    Returns:
        A mapping of service name to its busy limit in seconds.

    Raises:
        ValueError: If an entry is not ``service=seconds`` with positive
            seconds, or names a service that is not monitored (usually a typo
            that would otherwise silently do nothing).
    """
    overrides: dict[str, int] = {}
    raw_value = os.getenv("HEALTH_MAX_BUSY_OVERRIDES", "")
    for entry in (item.strip() for item in raw_value.split(",") if item.strip()):
        name, separator, seconds = entry.partition("=")
        name = name.strip()
        try:
            limit = int(seconds)
        except ValueError:
            limit = 0
        if not separator or limit <= 0:
            raise ValueError(
                "HEALTH_MAX_BUSY_OVERRIDES entries must look like "
                f"service=seconds with positive seconds, got {entry!r}"
            )
        if name not in monitored_services:
            raise ValueError(
                f"HEALTH_MAX_BUSY_OVERRIDES names unknown service {name!r}"
            )
        overrides[name] = limit
    return overrides


def load_settings() -> HealthMonitorSettings:
    """Load the monitor's Kafka endpoint and timing controls.

    Environment variables:
        KAFKA_BOOTSTRAP_SERVERS: Kafka broker address list.
        HEALTH_MONITORED_SERVICES: Optional comma-separated worker names.
        HEALTH_HEARTBEAT_TIMEOUT_SECONDS: Heartbeat expiry threshold.
        HEALTH_STARTUP_GRACE_SECONDS: Startup/recovery grace period.
        HEALTH_CHECK_INTERVAL_SECONDS: Poll and broker-check interval.
        HEALTH_MAX_BUSY_SECONDS: Longest one message may be in progress
            before a worker is reported as stuck.
        HEALTH_MAX_BUSY_OVERRIDES: Optional per-service limits written as
            ``service=seconds,service=seconds``.

    Returns:
        Settings for the health monitor.
    """
    configured_services = os.getenv("HEALTH_MONITORED_SERVICES")
    monitored_services = (
        tuple(
            dict.fromkeys(
                item.strip() for item in configured_services.split(",") if item.strip()
            )
        )
        if configured_services
        else DEFAULT_MONITORED_SERVICES
    )
    if not monitored_services:
        raise ValueError("HEALTH_MONITORED_SERVICES must name at least one service")

    return HealthMonitorSettings(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        monitored_services=monitored_services,
        heartbeat_timeout_seconds=_positive_int(
            "HEALTH_HEARTBEAT_TIMEOUT_SECONDS", 120
        ),
        startup_grace_seconds=_positive_int("HEALTH_STARTUP_GRACE_SECONDS", 180),
        check_interval_seconds=_positive_int("HEALTH_CHECK_INTERVAL_SECONDS", 10),
        max_busy_seconds=_positive_int("HEALTH_MAX_BUSY_SECONDS", 5400),
        busy_limit_overrides=_busy_overrides(monitored_services),
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

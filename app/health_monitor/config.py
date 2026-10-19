"""Pydantic-backed environment configuration for the health monitor."""

import logging
import os

from pydantic import ValidationError

from app.health_monitor.models import HealthMonitorEnvironment, HealthMonitorSettings


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

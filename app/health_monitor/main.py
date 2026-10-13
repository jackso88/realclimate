"""Command line entry point for Kafka and worker health monitoring."""

from app.health_monitor.config import load_settings
from app.health_monitor.monitor import run_health_monitor
from app.logging_config import configure_logging


def main() -> None:
    """Start the health monitor using environment configuration."""
    configure_logging()
    run_health_monitor(load_settings())


if __name__ == "__main__":
    main()

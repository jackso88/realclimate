"""Application-wide logging setup for command-line entry points."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure a concise, consistent log format for CLI applications."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

"""Application-wide logging setup for command-line entry points."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger with the application's standard log format.

    Args:
        level: Minimum logging severity to emit; defaults to ``logging.INFO``.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

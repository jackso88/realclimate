"""Environment configuration for the workflow orchestrator."""

import logging
import os
import socket

from app.orchestrator.models import OrchestratorSettings


def _positive_int(variable: str, default: int) -> int:
    """Read a positive integer environment value.

    Args:
        variable: Environment variable to read.
        default: Value used when the variable is unset.

    Returns:
        Parsed positive integer.

    Raises:
        ValueError: If the configured value is not positive or not an integer.
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


def load_settings() -> OrchestratorSettings:
    """Load RPC timeouts and derive this worker's response group identity.

    Returns:
        Settings used to call downloader, core, and uploader services.
    """
    return OrchestratorSettings(
        request_timeout_seconds=_positive_int("DOWNLOAD_TIMEOUT_SECONDS", 900),
        uploader_timeout_seconds=_positive_int("IMPORT_TIMEOUT_SECONDS", 1800),
        instance_id=os.getenv("ORCHESTRATOR_INSTANCE_ID", socket.gethostname()),
    )


def configure_logging(level: int = logging.INFO) -> None:
    """Configure this service's console log format.

    Args:
        level: Minimum log severity; defaults to INFO.
    """
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

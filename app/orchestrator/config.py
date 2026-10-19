"""Pydantic-backed environment configuration for the orchestrator."""

import logging
import os

from pydantic import ValidationError

from app.orchestrator.models import OrchestratorEnvironment, OrchestratorSettings


def load_settings() -> OrchestratorSettings:
    """Read and validate orchestrator timeout, identity, and broker settings.

    Returns:
        Validated settings used to call the worker services and run Kafka.

    Raises:
        ValueError: If a configured timeout is not a positive integer or the
            consumer identity is empty.
    """
    try:
        config = OrchestratorEnvironment.model_validate(dict(os.environ))
    except ValidationError as error:
        errors = error.errors()
        if errors:
            name = str(errors[0]["loc"][0])
            raise ValueError(
                f"{name} must be a positive integer or non-empty value"
            ) from error
        raise ValueError(f"Invalid orchestrator settings: {error}") from error
    return OrchestratorSettings(
        request_timeout_seconds=config.request_timeout_seconds,
        uploader_timeout_seconds=config.uploader_timeout_seconds,
        instance_id=config.instance_id,
        bootstrap_servers=config.bootstrap_servers,
        poll_interval_margin_seconds=config.poll_interval_margin_seconds,
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

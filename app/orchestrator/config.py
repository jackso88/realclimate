"""Pydantic-backed environment configuration for the orchestrator."""

import logging
import os
import socket

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
)

from app.orchestrator.models import OrchestratorSettings


class OrchestratorEnvironment(BaseModel):
    """Validated environment values consumed by the workflow orchestrator.

    Args:
        request_timeout_seconds: Positive timeout for downloader and core RPCs.
        uploader_timeout_seconds: Positive timeout for uploader completion.
        instance_id: Consumer identity isolating this process's RPC responses.
        bootstrap_servers: Kafka broker addresses for the worker.
        poll_interval_margin_seconds: Positive safety margin above worst-case
            run time.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    request_timeout_seconds: int = Field(
        default=900, validation_alias="DOWNLOAD_TIMEOUT_SECONDS", gt=0
    )
    uploader_timeout_seconds: int = Field(
        default=1800, validation_alias="IMPORT_TIMEOUT_SECONDS", gt=0
    )
    instance_id: str = Field(
        default_factory=lambda: socket.gethostname(),
        validation_alias="ORCHESTRATOR_INSTANCE_ID",
        min_length=1,
    )
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    poll_interval_margin_seconds: int = Field(
        default=600, validation_alias="ORCHESTRATOR_POLL_INTERVAL_MARGIN_SECONDS", gt=0
    )


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

"""Data transfer objects for workflow orchestration."""

import socket

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


class OrchestratorSettings(BaseModel):
    """Timeouts and identity used for downstream Kafka requests.

    Args:
        request_timeout_seconds: Timeout for each downloader and core request.
        uploader_timeout_seconds: Timeout for uploader completion.
        instance_id: Unique consumer identity used to isolate RPC replies.
        bootstrap_servers: Kafka broker addresses for the worker.
        poll_interval_margin_seconds: Safety delay added above worst-case run time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    request_timeout_seconds: int = Field(default=900, gt=0)
    uploader_timeout_seconds: int = Field(default=1800, ge=0)
    instance_id: str = Field(default="orchestrator", min_length=1)
    bootstrap_servers: str = Field(default="localhost:9092", min_length=1)
    poll_interval_margin_seconds: int = Field(default=600, gt=0)

    @property
    def worst_case_run_seconds(self) -> int:
        """Longest a run can take when every step uses its full timeout.

        A run waits for the reference download, the current download, and core
        processing (each bounded by ``request_timeout_seconds``), then for the
        uploader.

        Returns:
            The sum of those timeouts, in seconds.
        """
        return 3 * self.request_timeout_seconds + self.uploader_timeout_seconds


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

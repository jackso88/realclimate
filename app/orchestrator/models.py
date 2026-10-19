"""Data transfer objects for workflow orchestration."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OrchestratorSettings:
    """Timeouts and identity used for downstream Kafka requests.

    Args:
        request_timeout_seconds: Timeout for each downloader and core request.
        uploader_timeout_seconds: Timeout for uploader completion.
        instance_id: Unique consumer identity used to isolate RPC replies.
    """

    request_timeout_seconds: int = 900
    uploader_timeout_seconds: int = 1800
    instance_id: str = "orchestrator"

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

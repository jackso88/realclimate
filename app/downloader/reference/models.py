"""Data transfer objects for the Google Sheets downloader."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    """Validated spreadsheet and authentication configuration.

    Args:
        spreadsheet_url: Google Sheets URL or raw spreadsheet ID.
        sheet_name: Worksheet title to download.
        credentials_file: OAuth client secret used in ``user`` mode or for
            service-account permission fallback.
        token_file: Persisted user OAuth credentials used for refresh or fallback.
        auth_mode: Either ``user`` or ``service_account``.
        service_account_file: Service-account key JSON used in service mode.
        bootstrap_servers: Kafka broker addresses for the worker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    spreadsheet_url: str = Field(min_length=1)
    sheet_name: str = Field(min_length=1)
    credentials_file: Path | None = None
    token_file: Path | None = None
    auth_mode: Literal["user", "service_account"] = "user"
    service_account_file: Path | None = None
    bootstrap_servers: str = Field(default="localhost:9092", min_length=1)

    @model_validator(mode="after")
    def validate_auth_files(self) -> "Settings":
        """Require the credential files used by the configured auth mode."""
        if self.auth_mode == "user" and (
            self.credentials_file is None or self.token_file is None
        ):
            raise ValueError("user auth mode requires credentials and token files")
        if self.auth_mode == "service_account" and self.service_account_file is None:
            raise ValueError("service_account auth mode requires a key file")
        return self

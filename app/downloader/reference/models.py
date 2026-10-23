"""Data transfer objects for the Google Sheets downloader."""

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pathlib import Path
from typing import Literal


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


class ReferenceDownloaderEnvironment(BaseModel):
    """Validated environment values consumed by the reference downloader.

    Args:
        spreadsheet_url: Google Sheets URL or raw spreadsheet ID.
        sheet_name: Worksheet title to download.
        auth_mode: ``user`` for OAuth or ``service_account`` for service access.
        credentials_file: Optional OAuth client secret for user auth/fallback.
        token_file: Optional persisted OAuth token for user auth/fallback.
        service_account_file: Service-account key JSON used by service mode.
        bootstrap_servers: Kafka broker addresses for this worker.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    spreadsheet_url: str = Field(validation_alias="GOOGLE_SHEET_URL", min_length=1)
    sheet_name: str = Field(validation_alias="GOOGLE_SHEET_NAME", min_length=1)
    auth_mode: Literal["user", "service_account"] = Field(
        default="user", validation_alias="GOOGLE_AUTH_MODE"
    )
    credentials_file: Path | None = Field(
        default=None, validation_alias="GOOGLE_CREDENTIALS_FILE"
    )
    token_file: Path | None = Field(default=None, validation_alias="GOOGLE_TOKEN_FILE")
    service_account_file: Path | None = Field(
        default=None, validation_alias="GOOGLE_SERVICE_ACCOUNT_FILE"
    )
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )

    @field_validator("auth_mode", mode="before")
    @classmethod
    def normalize_auth_mode(cls, value: object) -> object:
        """Normalize user-provided auth mode to the supported lowercase form."""
        return value.strip().lower() if isinstance(value, str) else value

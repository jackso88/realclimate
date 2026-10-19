"""Data transfer objects used by the uploader service."""

from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)


class Settings(BaseModel):
    """Validated CMS settings for uploading and importing processed data.

    Args:
        ver_id: Positive CMS version identifier.
        access: CMS access parameter.
        shop_id: Positive CMS shop identifier.
        cms_url: CMS API base URL.
        bootstrap_servers: Kafka broker addresses for the worker.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    ver_id: int = Field(gt=0)
    access: str = Field(min_length=1)
    shop_id: int = Field(gt=0)
    cms_url: str = Field(min_length=1)
    bootstrap_servers: str = Field(default="localhost:9092", min_length=1)

    @field_validator("cms_url")
    @classmethod
    def validate_cms_url(cls, value: str) -> str:
        """Require an absolute HTTP or HTTPS CMS URL."""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CMS URL must use http:// or https://")
        return value.rstrip("/")


class UploadedFile(BaseModel):
    """Validated CMS file record created by uploading processed CSV data.

    Args:
        file_id: CMS identifier used for import and cleanup requests.
        filename: Name stored in the CMS file manager.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    file_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)


class ImportQueueItem(BaseModel):
    """Validated task number and current status from the CMS import queue.

    Args:
        cron_num: Positive CMS queue task number.
        status: Human-readable queue status.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    cron_num: int = Field(gt=0)
    status: str


class UploaderEnvironment(BaseModel):
    """Validated environment values consumed by the uploader service.

    Args:
        cms_url: HTTP or HTTPS CMS API base URL.
        shop_id: Positive CMS shop identifier.
        ver_id: Positive CMS version identifier.
        access: CMS access parameter, preserved without URL decoding.
        bootstrap_servers: Kafka broker addresses for this worker.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    cms_url: str = Field(validation_alias="TAPTOP_CMS_URL", min_length=1)
    shop_id: int = Field(validation_alias="TAPTOP_SHOP_ID", gt=0)
    ver_id: int = Field(validation_alias="TAPTOP_VER_ID", gt=0)
    access: str = Field(validation_alias="TAPTOP_ACCESS", min_length=1)
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )

"""Data models used by the current-data downloader."""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Settings(BaseModel):
    """Validated configuration for the current-catalogue downloader.

    Args:
        ver_id: Positive CMS version identifier.
        access: CMS access parameter.
        shop_id: Positive CMS shop identifier.
        cms_url: CMS API base URL.
        bootstrap_servers: Kafka broker addresses.
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


class DownloadedCsv(BaseModel):
    """CSV bytes and CMS archive metadata returned by an export.

    Args:
        cron_num: Positive queue task number which produced the archive.
        filename: Name of the CSV member inside the archive.
        content: Raw CSV data, kept in memory.
        archive_filename: Name of the downloaded ZIP archive.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cron_num: int = Field(gt=0)
    filename: str = Field(min_length=1)
    content: bytes
    archive_filename: str = Field(min_length=1)

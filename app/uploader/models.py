"""Data transfer objects used by the uploader service."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """CMS shop and endpoint settings; admin_auth owns login credentials."""

    ver_id: int
    access: str
    shop_id: int
    cms_url: str


@dataclass(frozen=True)
class UploadedFile:
    """Admin file record created by uploading the processed CSV."""

    file_id: str
    filename: str


@dataclass(frozen=True)
class ImportQueueItem:
    """An import task's number and current status from the CMS queue."""

    cron_num: int
    status: str

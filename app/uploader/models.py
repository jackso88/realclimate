"""Data transfer objects used by the uploader service."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """CMS login, endpoint, and local processed-file settings."""

    ver_id: int
    access: str
    shop_id: int
    cms_url: str
    base_url: str
    username: str
    password: str
    design_id: int
    processed_file: Path
    login_path: str = "/login"
    mosaic_path: str = "/mosaic"
    form_name: str = "login_form"
    username_field: str = "email"
    password_field: str = "password"


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

"""Data models used by the current-data downloader."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from the project dotenv file.

    Attributes:
        ver_id: Admin version ID.
        access: Admin access value.
        shop_id: Shop identifier used for product export.
        cms_url: Base URL for CMS endpoints.
        base_url: Base URL for the login endpoint.
        username: Account name used by the login form.
        password: Account password used by the login form.
        design_id: CMS design ID used to initialize the admin context.
        login_path: Path that starts the login flow.
        mosaic_path: CMS mosaic initialization path.
        form_name: Value sent in the login form's ``_form`` field.
        username_field: HTML form field for the account email or username.
        password_field: HTML form field for the password.
    """

    ver_id: int
    access: str
    shop_id: int
    cms_url: str
    base_url: str
    username: str
    password: str
    design_id: int
    login_path: str = "/login"
    mosaic_path: str = "/mosaic"
    form_name: str = "login_form"
    username_field: str = "email"
    password_field: str = "password"


@dataclass(frozen=True)
class DownloadedExport:
    """Identify the downloaded export and its local archive.

    Attributes:
        cron_num: Numeric task number displayed in the admin queue.
        archive_filename: Name of the ZIP file in the admin file manager.
        archive_path: Local path to the downloaded ZIP file.
        archive_url: URL from which the ZIP file was downloaded.
    """

    cron_num: int
    archive_filename: str
    archive_path: Path
    archive_url: str

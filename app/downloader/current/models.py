"""Data models used by the current-data downloader."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """CMS shop identifiers used by the export service."""

    ver_id: int
    access: str
    shop_id: int
    cms_url: str


@dataclass(frozen=True)
class DownloadedCsv:
    """CSV bytes and source archive metadata returned by an export."""

    cron_num: int
    filename: str
    content: bytes
    archive_filename: str

"""Tests for in-memory admin export processing and remote cleanup."""

from io import BytesIO
from unittest.mock import Mock, patch
from zipfile import ZipFile

import pytest

from app.downloader.current.config import Settings
from app.downloader.current.exceptions import ExportArchiveError, ExportNotReadyError
from app.downloader.current.queue_processor import (
    delete_archive_from_admin,
    download_latest_export_content,
    find_latest_export_archive,
    find_latest_queue_cron_num,
    start_product_export,
)


def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Build a ZIP fixture fully in memory."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def make_settings() -> Settings:
    """Return settings with synthetic test identifiers."""
    return Settings(
        ver_id=21,
        access="u%3Btest",
        shop_id=11,
        cms_url="https://cms.example/-/cms/v1/",
    )


def test_selects_highest_queue_number_with_zip_link():
    html = """
    <div class="cron-list-item"><span class="cron-num">#7</span>
      <span class="cron-link"><a href="/files/old.zip">old</a></span></div>
    <div class="cron-list-item"><span class="cron-num">#42</span>
      <span class="cron-link"><a href="/files/new.zip">new</a></span></div>
    """
    assert find_latest_export_archive(html, make_settings()) == (
        42,
        "https://cms.example/files/new.zip",
    )


def test_queue_without_downloadable_archive_is_not_ready():
    with pytest.raises(ExportNotReadyError):
        find_latest_export_archive('<div class="cron-num">#9</div>', make_settings())


def test_queue_snapshot_includes_newer_running_job_without_zip_link():
    html = """
    <div class="cron-list-item"><span class="cron-num">#17</span>
      <span class="cron-link"><a href="/files/finished.zip">finished</a></span>
    </div>
    <div class="cron-list-item"><span class="cron-num">#29</span>
      <span class="cron-status">Выполняется</span>
    </div>
    """

    assert find_latest_queue_cron_num(html) == 29


def test_export_csv_is_returned_in_memory_and_admin_archive_is_cleaned():
    session = Mock()
    queue_response = Mock(
        text=(
            '<div class="cron-list-item"><span class="cron-num">#22</span>'
            '<span class="cron-link"><a href="/files/export-test.zip">zip</a></span>'
            "</div>"
        )
    )
    queue_response.raise_for_status.return_value = None
    archive_response = Mock(
        content=make_zip_bytes({"products.csv": b"article;price\nTEST;1\n"})
    )
    archive_response.raise_for_status.return_value = None
    session.get.side_effect = [queue_response, archive_response]

    downloaded = download_latest_export_content(
        session, make_settings(), after_cron_num=21
    )

    assert downloaded.content == b"article;price\nTEST;1\n"
    assert downloaded.filename == "products.csv"
    assert downloaded.archive_filename == "export-test.zip"


def test_export_rejects_zip_without_csv_member():
    session = Mock()
    session.get.side_effect = [
        Mock(
            text=(
                '<div class="cron-list-item"><span class="cron-num">#22</span>'
                '<span class="cron-link"><a href="/files/export-test.zip">zip</a>'
                "</span></div>"
            ),
            raise_for_status=Mock(),
        ),
        Mock(content=make_zip_bytes({"notes.txt": b"none"}), raise_for_status=Mock()),
    ]
    with pytest.raises(ExportArchiveError, match="exactly one CSV"):
        download_latest_export_content(session, make_settings(), after_cron_num=21)


def test_product_export_request_uses_form_payload():
    session = Mock()
    response = Mock()
    session.post.return_value = response
    assert start_product_export(session, make_settings()) is response
    assert ("format", "csv") in session.post.call_args.kwargs["data"]


@patch("app.downloader.current.queue_processor.secrets.randbelow", return_value=42)
def test_admin_archive_is_deleted_by_file_id(_random_value):
    session = Mock()
    listing = Mock(
        text=(
            '<input name="file_json" value=\'{"file_id":"file-test",'
            '"name":"export-test.zip","filename":"export-test.zip"}\'>'
        )
    )
    listing.raise_for_status.return_value = None
    deleted = Mock()
    deleted.raise_for_status.return_value = None
    session.get.side_effect = [listing, deleted]

    assert delete_archive_from_admin(session, make_settings(), "export-test.zip") == (
        "file-test"
    )
    assert ("object_id", "file-test") in session.get.call_args_list[1].kwargs["params"]

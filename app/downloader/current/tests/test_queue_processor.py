"""Tests for selecting, downloading, and extracting queued product exports."""

from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

import requests

from app.downloader.current.config import Settings
from app.downloader.current.queue_processor import (
    EXPORT_METADATA_FILENAME,
    ExportArchiveError,
    ExportNotReadyError,
    download_latest_export,
    extract_export_csv,
    find_latest_export_archive,
)

SETTINGS = Settings(
    base_url="https://example.test",
    username="alice",
    password="pw",
    shop_id=1234,
    ver_id=12345678,
    access="u;123456",
    cms_url="https://cms.test/",
    design_id=4321,
)


def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP fixture from member names and byte contents."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


class FindLatestExportTests(TestCase):
    """Verify queue rows are ordered by numeric cron number, not HTML order."""

    def test_returns_highest_cron_number_with_a_zip_link(self):
        html = """
        <div class="cron-list-item">
          <span class="cron-num">#9</span>
          <span class="cron-link"><a href="/files/old.zip">old.zip</a></span>
        </div>
        <div class="cron-list-item">
          <span class="cron-num">#120</span>
          <span class="cron-link"><a href="https://files.example/new.zip">new.zip</a></span>
        </div>
        <div class="cron-list-item">
          <span class="cron-num">#999</span>
          <span class="cron-link">No download yet</span>
        </div>
        """

        self.assertEqual(
            find_latest_export_archive(html, SETTINGS),
            (120, "https://files.example/new.zip"),
        )

    def test_raises_when_no_row_has_a_zip_link(self):
        html = '<div class="cron-list-item"><span class="cron-num">#45</span></div>'

        with self.assertRaises(ExportNotReadyError):
            find_latest_export_archive(html, SETTINGS)

    def test_ignores_malformed_cron_numbers(self):
        html = """
        <div class="cron-list-item">
          <span class="cron-num">#not-a-number</span>
          <span class="cron-link"><a href="/files/invalid.zip">file</a></span>
        </div>
        """

        with self.assertRaises(ExportNotReadyError):
            find_latest_export_archive(html, SETTINGS)


class DownloadLatestExportTests(TestCase):
    """Verify the newest linked ZIP is fetched and its metadata is retained."""

    def setUp(self):
        # These are synthetic test values, not identifiers from the live site.
        self.settings = Settings(
            ver_id=202,
            access="u%3Btest",
            shop_id=101,
            cms_url="https://cms.example",
            base_url="https://admin.example",
            username="test-user",
            password="test-password",
            design_id=303,
        )
        self.session = Mock()
        self.queue_response = Mock(text="""
            <div class="cron-list-item">
              <span class="cron-num">#7</span>
              <span class="cron-link"><a href="/files/older.zip">older.zip</a></span>
            </div>
            <div class="cron-list-item">
              <span class="cron-num">#42</span>
              <span class="cron-link"><a href="/files/latest.zip">latest.zip</a></span>
            </div>
            """)
        self.queue_response.raise_for_status.return_value = None
        self.archive_response = Mock(
            content=make_zip_bytes({"products.csv": b"sku;name\n1;item\n"})
        )
        self.archive_response.raise_for_status.return_value = None
        self.session.get.side_effect = [self.queue_response, self.archive_response]

    def test_downloads_highest_cron_archive_and_writes_metadata(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            export = download_latest_export(self.session, self.settings, upload_dir)

            self.assertEqual(export.cron_num, 42)
            self.assertEqual(export.archive_url, "https://cms.example/files/latest.zip")
            self.assertEqual(export.archive_path, upload_dir / "latest.zip")
            self.assertEqual(
                export.archive_path.read_bytes(), self.archive_response.content
            )
            self.assertEqual(
                export.metadata_path, upload_dir / EXPORT_METADATA_FILENAME
            )
            self.assertEqual(
                json.loads(export.metadata_path.read_text(encoding="utf-8")),
                {
                    "cron_num": 42,
                    "archive_filename": "latest.zip",
                    "archive_url": "https://cms.example/files/latest.zip",
                },
            )

        self.assertEqual(self.session.get.call_count, 2)
        queue_call, archive_call = self.session.get.call_args_list
        self.assertEqual(queue_call.args, ("https://cms.example/shop2/",))
        self.assertEqual(
            dict(queue_call.kwargs["params"]),
            {
                "act": "view",
                "object_id": "101",
                "ver_id": "202",
                "access": "u;test",
            }
            | {"rnd": queue_call.kwargs["params"][-1][1]},
        )
        self.assertEqual(archive_call.args, ("https://cms.example/files/latest.zip",))
        self.assertEqual(queue_call.kwargs["timeout"], 30)

    def test_raises_on_failed_queue_response(self):
        self.queue_response.raise_for_status.side_effect = requests.HTTPError(
            "forbidden"
        )

        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            with self.assertRaises(requests.HTTPError):
                download_latest_export(self.session, self.settings, upload_dir)

        self.assertEqual(self.session.get.call_count, 1)


class ExtractExportCsvTests(TestCase):
    """Verify a CSV member is written as storage/uploads/current.csv."""

    def test_extracts_nested_csv_member_to_current_csv(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            archive_path = upload_dir / "export.zip"
            archive_path.write_bytes(
                make_zip_bytes({"folder/products.csv": b"id;name\n1;test\n"})
            )

            csv_path = extract_export_csv(archive_path, upload_dir)

            self.assertEqual(csv_path, upload_dir / "current.csv")
            self.assertEqual(csv_path.read_bytes(), b"id;name\n1;test\n")

    def test_rejects_zip_without_exactly_one_csv(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            archive_path = upload_dir / "export.zip"
            archive_path.write_bytes(make_zip_bytes({"readme.txt": b"nothing"}))

            with self.assertRaisesRegex(ExportArchiveError, "found 0"):
                extract_export_csv(archive_path, upload_dir)

    def test_does_not_extract_to_path_from_zip_member(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            archive_path = upload_dir / "export.zip"
            archive_path.write_bytes(make_zip_bytes({"../../outside.csv": b"safe"}))

            csv_path = extract_export_csv(archive_path, upload_dir)

            self.assertEqual(csv_path, upload_dir / "current.csv")
            self.assertEqual(csv_path.read_bytes(), b"safe")

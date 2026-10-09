"""Tests for selecting, downloading, and deleting admin exports."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

import requests

from app.downloader.current.config import Settings
from app.downloader.current.exceptions import (
    AdminFileNotFoundError,
    ExportArchiveError,
    ExportNotReadyError,
)
from app.downloader.current.queue_processor import (
    delete_archive_from_admin,
    download_latest_export,
    find_latest_export_archive,
)


def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Build an in-memory ZIP fixture from member names and byte contents."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


def make_settings() -> Settings:
    """Return settings with synthetic identifiers for isolated tests."""
    return Settings(
        ver_id=202,
        access="u%3Btest",
        shop_id=101,
        cms_url="https://cms.example/-/cms/v1/",
        base_url="https://admin.example",
        username="test-user",
        password="test-password",
        design_id=303,
    )


class FindLatestExportTests(TestCase):
    """Verify queue rows are selected by numeric cron number."""

    def test_returns_highest_cron_number_with_a_zip_link(self):
        html = """
        <div class="cron-list-item">
          <span class="cron-num">#9</span>
          <span class="cron-link"><a href="/f/old.zip">old.zip</a></span>
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
            find_latest_export_archive(html, make_settings()),
            (120, "https://files.example/new.zip"),
        )

    def test_raises_when_no_row_has_a_zip_link(self):
        html = '<div class="cron-list-item"><span class="cron-num">#45</span></div>'

        with self.assertRaises(ExportNotReadyError):
            find_latest_export_archive(html, make_settings())

    def test_ignores_malformed_cron_numbers(self):
        html = """
        <div class="cron-list-item">
          <span class="cron-num">#not-a-number</span>
          <span class="cron-link"><a href="/f/invalid.zip">file</a></span>
        </div>
        """

        with self.assertRaises(ExportNotReadyError):
            find_latest_export_archive(html, make_settings())


class DownloadLatestExportTests(TestCase):
    """Verify downloading returns the archive name without a sidecar JSON."""

    def setUp(self):
        self.settings = make_settings()
        self.session = Mock()
        self.queue_response = Mock(
            text="""
            <div class="cron-list-item">
              <span class="cron-num">#7</span>
              <span class="cron-link"><a href="/f/older.zip">older.zip</a></span>
            </div>
            <div class="cron-list-item">
              <span class="cron-num">#42</span>
              <span class="cron-link"><a href="/f/latest.zip">latest.zip</a></span>
            </div>
            """
        )
        self.queue_response.raise_for_status.return_value = None
        self.archive_response = Mock(
            content=make_zip_bytes({"products.csv": b"sku;name\n1;item\n"})
        )
        self.archive_response.raise_for_status.return_value = None
        self.session.get.side_effect = [self.queue_response, self.archive_response]

    def test_downloads_highest_cron_archive_and_returns_its_name(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            downloaded = download_latest_export(
                self.session, self.settings, upload_dir
            )

            self.assertEqual(downloaded.cron_num, 42)
            self.assertEqual(downloaded.archive_filename, "latest.zip")
            self.assertEqual(
                downloaded.archive_url,
                "https://cms.example/f/latest.zip",
            )
            self.assertEqual(downloaded.archive_path, upload_dir / "latest.zip")
            self.assertEqual(
                downloaded.archive_path.read_bytes(), self.archive_response.content
            )
            self.assertFalse((upload_dir / "latest_export.json").exists())

        queue_call, archive_call = self.session.get.call_args_list
        self.assertEqual(
            queue_call.args,
            ("https://cms.example/-/cms/v1/shop2/",),
        )
        self.assertEqual(
            queue_call.kwargs["params"],
            [
                ("act", "view"),
                ("object_id", "101"),
                ("ver_id", "202"),
                ("access", "u;test"),
                ("rnd", queue_call.kwargs["params"][-1][1]),
            ],
        )
        self.assertEqual(
            archive_call.args,
            ("https://cms.example/f/latest.zip",),
        )

    def test_raises_on_failed_queue_response(self):
        self.queue_response.raise_for_status.side_effect = requests.HTTPError(
            "forbidden"
        )

        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(requests.HTTPError):
                download_latest_export(self.session, self.settings, temp_dir)

        self.assertEqual(self.session.get.call_count, 1)

    @patch("app.downloader.current.queue_processor.sleep")
    @patch("app.downloader.current.queue_processor.monotonic", return_value=0)
    def test_waits_for_queue_entry_newer_than_the_baseline(
        self, _monotonic_mock, sleep_mock
    ):
        old_queue = Mock(
            text=(
                '<div class="cron-list-item"><span class="cron-num">#42</span>'
                '<span class="cron-link"><a href="/f/old.zip">old</a></span></div>'
            )
        )
        old_queue.raise_for_status.return_value = None
        new_queue = Mock(
            text=(
                '<div class="cron-list-item"><span class="cron-num">#43</span>'
                '<span class="cron-link"><a href="/f/new.zip">new</a></span></div>'
            )
        )
        new_queue.raise_for_status.return_value = None
        self.session.get.side_effect = [old_queue, new_queue, self.archive_response]

        with TemporaryDirectory() as temp_dir:
            downloaded = download_latest_export(
                self.session,
                self.settings,
                temp_dir,
                after_cron_num=42,
                poll_interval=0,
            )

        self.assertEqual(downloaded.cron_num, 43)
        self.assertEqual(downloaded.archive_filename, "new.zip")
        sleep_mock.assert_called_once_with(0)
        self.assertEqual(self.session.get.call_count, 3)


class DeleteArchiveFromAdminTests(TestCase):
    """Verify file_json lookup and GET deletion use the CMS URL in settings."""

    def setUp(self):
        self.settings = make_settings()
        self.session = Mock()
        unrelated = '{"file_id":"505","name":"other.zip","filename":"other.zip"}'
        target = '{"file_id":"707","name":"export.zip","filename":"export.zip"}'
        listing = Mock(
            text=(
                '<input name="file_json" value=\'' + unrelated + '\'>'
                '<input name="file_json" value=\'' + target + '\'>'
            )
        )
        listing.raise_for_status.return_value = None
        self.listing_response = listing
        deleted = Mock()
        deleted.raise_for_status.return_value = None
        self.deleted_response = deleted
        self.session.get.side_effect = [listing, deleted]

    @patch("app.downloader.current.queue_processor.secrets.randbelow", return_value=42)
    def test_finds_file_id_and_sends_delete_request(self, _random_value):
        file_id = delete_archive_from_admin(
            self.session,
            self.settings,
            "export.zip",
        )

        self.assertEqual(file_id, "707")
        listing_call, delete_call = self.session.get.call_args_list
        expected_url = "https://cms.example/-/cms/v1/file/"
        self.assertEqual(listing_call.args, (expected_url,))
        self.assertEqual(
            listing_call.kwargs["params"],
            [
                ("popup", "1"),
                ("selector", "1"),
                ("multiple", "false"),
                ("ver_id", "202"),
                ("access", "u;test"),
                ("type_group_id", "0"),
                ("rnd", "1042"),
                ("xhr", "1"),
            ],
        )
        self.assertEqual(delete_call.args, (expected_url,))
        self.assertEqual(
            delete_call.kwargs["params"],
            [
                ("act", "delete"),
                ("ver_id", "202"),
                ("access", "u;test"),
                ("popup", "1"),
                ("object_id", "707"),
                ("rnd", "1042"),
                ("xhr", "1"),
            ],
        )
        self.listing_response.raise_for_status.assert_called_once_with()
        self.deleted_response.raise_for_status.assert_called_once_with()

    def test_raises_when_archive_name_is_not_in_file_listing(self):
        listing = Mock(
            text=(
                '<input name="file_json" '
                'value=\'{"file_id":"9","filename":"other.zip"}\'>'
            )
        )
        listing.raise_for_status.return_value = None
        self.session.get.side_effect = [listing]

        with self.assertRaises(AdminFileNotFoundError):
            delete_archive_from_admin(self.session, self.settings, "missing.zip")

        self.assertEqual(self.session.get.call_count, 1)

"""Tests for the end-to-end current product export call sequence."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from app.downloader.current.cli import main
from app.downloader.current.models import DownloadedExport


class MainTests(TestCase):
    """Verify CLI orchestration follows the required cleanup order."""

    @patch("app.downloader.current.cli.logger.info")
    @patch("app.downloader.current.cli.clear_auth_session_cache")
    @patch("app.downloader.current.cli.delete_archive_from_admin")
    @patch("app.downloader.current.cli.delete_local_archive")
    @patch("app.downloader.current.cli.extract_export_csv")
    @patch("app.downloader.current.cli.download_latest_export")
    @patch("app.downloader.current.cli.start_product_export")
    @patch("app.downloader.current.cli.get_latest_export_cron_num")
    @patch("app.downloader.current.cli.get_auth_session")
    @patch("app.downloader.current.cli.load_settings")
    def test_runs_export_then_local_and_remote_cleanup(
        self,
        load_settings_mock,
        get_session_mock,
        get_latest_cron_mock,
        start_export_mock,
        download_mock,
        extract_mock,
        delete_local_mock,
        delete_admin_mock,
        clear_cache_mock,
        log_info_mock,
    ):
        events = []
        session = Mock()
        settings = Mock()
        load_settings_mock.side_effect = lambda: events.append("settings") or settings
        get_session_mock.side_effect = lambda: events.append("session") or session
        get_latest_cron_mock.side_effect = lambda *_: events.append("baseline") or 41

        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "synthetic-export.zip"
            csv_path = Path(temp_dir) / "current.csv"
            downloaded = DownloadedExport(
                cron_num=42,
                archive_filename="synthetic-export.zip",
                archive_path=archive_path,
                archive_url="https://files.example/synthetic-export.zip",
            )
            start_export_mock.side_effect = lambda *_: events.append("submit")
            download_mock.side_effect = (
                lambda *_, **__: events.append("download") or downloaded
            )
            extract_mock.side_effect = lambda *_: events.append("extract") or csv_path
            delete_local_mock.side_effect = lambda *_: events.append("local-delete")
            delete_admin_mock.side_effect = (
                lambda *_: events.append("admin-delete") or "file-707"
            )
            clear_cache_mock.side_effect = lambda: events.append("clear-cache")

            main()

        self.assertEqual(
            events,
            [
                "settings",
                "session",
                "baseline",
                "submit",
                "download",
                "extract",
                "local-delete",
                "admin-delete",
                "clear-cache",
            ],
        )
        load_settings_mock.assert_called_once_with()
        get_session_mock.assert_called_once_with()
        get_latest_cron_mock.assert_called_once_with(session, settings)
        start_export_mock.assert_called_once_with(session, settings)
        download_mock.assert_called_once_with(
            session,
            settings,
            after_cron_num=41,
        )
        extract_mock.assert_called_once_with(archive_path)
        delete_local_mock.assert_called_once_with(archive_path)
        delete_admin_mock.assert_called_once_with(
            session,
            settings,
            "synthetic-export.zip",
        )
        clear_cache_mock.assert_called_once_with()
        self.assertGreater(log_info_mock.call_count, 0)

    @patch("app.downloader.current.cli.clear_auth_session_cache")
    @patch("app.downloader.current.cli.start_product_export")
    @patch("app.downloader.current.cli.get_latest_export_cron_num")
    @patch("app.downloader.current.cli.get_auth_session")
    @patch("app.downloader.current.cli.load_settings")
    def test_clears_auth_session_when_export_fails(
        self,
        load_settings_mock,
        get_session_mock,
        get_latest_cron_mock,
        start_export_mock,
        clear_cache_mock,
    ):
        get_session_mock.return_value = Mock()
        get_latest_cron_mock.return_value = 41
        start_export_mock.side_effect = RuntimeError("submission failed")

        with self.assertRaisesRegex(RuntimeError, "submission failed"):
            main()

        clear_cache_mock.assert_called_once_with()

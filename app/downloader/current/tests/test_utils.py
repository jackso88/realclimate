"""Tests for local archive extraction and cleanup utilities."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from zipfile import ZipFile

from app.downloader.current.exceptions import ExportArchiveError
from app.downloader.current.utils import delete_local_archive, extract_export_csv


def make_zip_bytes(files: dict[str, bytes]) -> bytes:
    """Create an in-memory ZIP archive for utility tests."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return buffer.getvalue()


class ExtractExportCsvTests(TestCase):
    """Verify CSV extraction writes only the requested local destination."""

    def test_extracts_csv_member_as_current_csv(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            archive_path = upload_dir / "export.zip"
            archive_path.write_bytes(
                make_zip_bytes({"nested/products.csv": b"sku;name\n1;item\n"})
            )

            csv_path = extract_export_csv(archive_path, upload_dir)

            self.assertEqual(csv_path, upload_dir / "current.csv")
            self.assertEqual(csv_path.read_bytes(), b"sku;name\n1;item\n")

    def test_rejects_archives_without_exactly_one_csv(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            archive_path = upload_dir / "export.zip"
            archive_path.write_bytes(make_zip_bytes({"readme.txt": b"no csv"}))

            with self.assertRaisesRegex(ExportArchiveError, "found 0"):
                extract_export_csv(archive_path, upload_dir)

    def test_prevents_zip_member_path_traversal(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir) / "uploads"
            archive_path = Path(temp_dir) / "export.zip"
            archive_path.write_bytes(make_zip_bytes({"../../outside.csv": b"safe"}))

            csv_path = extract_export_csv(archive_path, upload_dir)

            self.assertEqual(csv_path, upload_dir / "current.csv")
            self.assertEqual(csv_path.read_bytes(), b"safe")
            self.assertFalse((Path(temp_dir) / "outside.csv").exists())

    def test_rejects_invalid_zip(self):
        with TemporaryDirectory() as temp_dir:
            upload_dir = Path(temp_dir)
            archive_path = upload_dir / "invalid.zip"
            archive_path.write_bytes(b"not a zip")

            with self.assertRaises(ExportArchiveError):
                extract_export_csv(archive_path, upload_dir)


class DeleteLocalArchiveTests(TestCase):
    """Verify the downloaded ZIP can be removed after extraction."""

    def test_deletes_archive_file(self):
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "export.zip"
            archive_path.write_bytes(b"archive")

            delete_local_archive(archive_path)

            self.assertFalse(archive_path.exists())

    def test_reports_when_archive_file_is_missing(self):
        with TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "missing.zip"

            with self.assertRaises(FileNotFoundError):
                delete_local_archive(archive_path)

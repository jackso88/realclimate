"""Local archive utilities for the current-data downloader."""

from pathlib import Path
import shutil
from zipfile import BadZipFile, ZipFile

from app.downloader.current.exceptions import ExportArchiveError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "storage" / "uploads"


def extract_export_csv(
    archive_path: str | Path,
    upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
) -> Path:
    """Write the only CSV member in an export ZIP as ``current.csv``.

    The member is copied directly to the destination instead of extracting its
    archive path, so path traversal entries cannot write outside ``upload_dir``.

    Args:
        archive_path: Path to a downloaded ZIP archive.
        upload_dir: Destination directory; defaults to ``storage/uploads``.

    Returns:
        Path to the resulting ``current.csv`` file.

    Raises:
        ExportArchiveError: If the ZIP is invalid or does not contain exactly
            one CSV file.
    """
    output_dir = Path(upload_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "current.csv"
    temporary_csv = output_dir / "current.csv.part"

    try:
        with ZipFile(archive_path) as archive:
            csv_members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".csv")
            ]
            if len(csv_members) != 1:
                raise ExportArchiveError(
                    f"Expected exactly one CSV member in ZIP, found {len(csv_members)}"
                )

            with archive.open(csv_members[0]) as source, temporary_csv.open(
                "wb"
            ) as target:
                shutil.copyfileobj(source, target)
    except BadZipFile as error:
        raise ExportArchiveError(
            "The downloaded export is not a valid ZIP archive"
        ) from error

    temporary_csv.replace(csv_path)
    return csv_path


def delete_local_archive(archive_path: str | Path) -> None:
    """Remove a downloaded archive from local storage after extraction.

    Args:
        archive_path: ZIP archive to remove.

    Raises:
        FileNotFoundError: If the archive does not exist.
        OSError: If the operating system cannot remove the archive.
    """
    Path(archive_path).unlink()

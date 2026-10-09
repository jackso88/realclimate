"""Run one complete product export and cleanup cycle."""

from app.downloader.current.auth import clear_auth_session_cache, get_auth_session
from app.downloader.current.config import load_settings
from app.downloader.current.queue_processor import (
    delete_archive_from_admin,
    download_latest_export,
    get_latest_export_cron_num,
    start_product_export,
)
from app.downloader.current.utils import delete_local_archive, extract_export_csv


def main() -> None:
    """Create an export, download and unpack it, then clean up both archives."""
    settings = load_settings()
    session = get_auth_session()

    try:
        previous_cron_num = get_latest_export_cron_num(session, settings)
        start_product_export(session, settings)
        downloaded_export = download_latest_export(
            session,
            settings,
            after_cron_num=previous_cron_num,
        )
        csv_path = extract_export_csv(downloaded_export.archive_path)
        delete_local_archive(downloaded_export.archive_path)
        file_id = delete_archive_from_admin(
            session,
            settings,
            downloaded_export.archive_filename,
        )
        print(
            "Export complete: "
            f"cron #{downloaded_export.cron_num}, "
            f"CSV saved to {csv_path}, "
            f"admin file {file_id} removed."
        )
    finally:
        clear_auth_session_cache()


if __name__ == "__main__":
    main()

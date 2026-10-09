"""Run one complete product export and cleanup cycle."""

import logging

from app.downloader.current.auth import clear_auth_session_cache, get_auth_session
from app.downloader.current.config import load_settings
from app.downloader.current.queue_processor import (
    delete_archive_from_admin,
    download_latest_export,
    get_latest_export_cron_num,
    start_product_export,
)
from app.downloader.current.utils import delete_local_archive, extract_export_csv
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Create an export, download and unpack it, then clean up both archives."""
    configure_logging()
    settings = load_settings()
    session = get_auth_session()

    try:
        logger.info("Reading current export queue state")
        previous_cron_num = get_latest_export_cron_num(session, settings)
        logger.info("Submitting product export request")
        start_product_export(session, settings)
        logger.info("Waiting for and downloading the new export")
        downloaded_export = download_latest_export(
            session,
            settings,
            after_cron_num=previous_cron_num,
        )
        logger.info("Extracting %s", downloaded_export.archive_filename)
        csv_path = extract_export_csv(downloaded_export.archive_path)
        logger.info("Removing local archive %s", downloaded_export.archive_path)
        delete_local_archive(downloaded_export.archive_path)
        logger.info("Removing archive from the admin file manager")
        file_id = delete_archive_from_admin(
            session,
            settings,
            downloaded_export.archive_filename,
        )
        logger.info(
            "Export complete: cron #%s, CSV saved to %s, admin file %s removed",
            downloaded_export.cron_num,
            csv_path,
            file_id,
        )
    except Exception:
        logger.exception("Product export pipeline failed")
        raise
    finally:
        clear_auth_session_cache()


if __name__ == "__main__":
    main()

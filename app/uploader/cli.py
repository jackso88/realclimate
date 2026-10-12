"""Run the upload, import-queue, wait, and admin cleanup workflow."""

import logging

from app.logging_config import configure_logging
from app.uploader.auth import clear_auth_session_cache, get_auth_session
from app.uploader.config import load_settings
from app.uploader.queue_processor import (
    delete_uploaded_file,
    get_latest_import_cron_num,
    start_product_import,
    upload_processed_file,
    wait_for_import_completion,
)

logger = logging.getLogger(__name__)


def main() -> None:
    """Upload the processed CSV, import it, then remove its admin file."""
    configure_logging()
    settings = load_settings()
    session = get_auth_session()

    try:
        uploaded_file = upload_processed_file(
            session,
            settings,
            settings.processed_file,
        )
        baseline_cron_num = get_latest_import_cron_num(session, settings)
        start_product_import(session, settings, uploaded_file)
        completed_task = wait_for_import_completion(
            session,
            settings,
            baseline_cron_num,
        )
        delete_uploaded_file(session, settings, uploaded_file)
        logger.info(
            "Processed file import completed: cron #%s, file %s",
            completed_task.cron_num,
            uploaded_file.filename,
        )
    except Exception:
        logger.exception("Processed CSV upload/import pipeline failed")
        raise
    finally:
        clear_auth_session_cache()


if __name__ == "__main__":
    main()

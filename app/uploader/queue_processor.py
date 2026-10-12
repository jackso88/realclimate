"""Upload CSV files and submit or monitor CMS product import tasks."""

import logging
from io import BytesIO
from pathlib import Path
from time import monotonic, sleep, time

import requests

from app.uploader.exceptions import ImportQueueError, UploadFileError
from app.uploader.models import ImportQueueItem, Settings, UploadedFile
from app.uploader.utils import (
    access_value,
    admin_url,
    ensure_import_succeeded,
    extract_uploaded_file_id,
    latest_cron_num,
    newest_task_after,
    random_query_value,
)

logger = logging.getLogger(__name__)
MAX_UPLOAD_SIZE = 67_108_864


def upload_processed_content(
    session: requests.Session,
    settings: Settings,
    content: bytes,
    filename: str = "processed.csv",
    timeout: float = 60,
) -> UploadedFile:
    """Upload CSV bytes as multipart form data and return the admin file ID."""
    if len(content) > MAX_UPLOAD_SIZE:
        raise UploadFileError(
            f"Processed CSV exceeds the CMS upload limit of {MAX_UPLOAD_SIZE} bytes"
        )

    path = Path(filename)
    access = access_value(settings)
    upload_params = [
        ("act", "edit"),
        ("ver_id", str(settings.ver_id)),
        ("access", access),
        ("popup", "1"),
        ("orderby", "created"),
        ("time", str(int(time() * 1000))),
    ]
    form_data = [
        ("ver_id", str(settings.ver_id)),
        ("access", access),
        ("query_id", "0"),
        ("global", ""),
        ("MAX_FILE_SIZE", str(MAX_UPLOAD_SIZE)),
        ("folder_ids", ""),
        ("names", path.stem),
    ]

    response = session.post(
        admin_url(settings, "file/"),
        params=upload_params,
        data=form_data,
        files={
            "files": (
                path.name,
                BytesIO(content),
                "text/csv",
            )
        },
        timeout=timeout,
    )

    response.raise_for_status()
    file_id = extract_uploaded_file_id(response.text, path.name)
    logger.info("Uploaded %s to CMS file manager as file_id=%s", path.name, file_id)
    return UploadedFile(file_id=file_id, filename=path.name)


def get_latest_import_cron_num(
    session: requests.Session,
    settings: Settings,
    timeout: float = 30,
) -> int:
    """Read the current highest queue number before submitting an import."""
    response = session.get(
        admin_url(settings, "shop2/"),
        params=_shop_view_params(settings),
        timeout=timeout,
    )
    response.raise_for_status()
    return latest_cron_num(response.text)


def _shop_view_params(settings: Settings) -> list[tuple[str, str]]:
    """Build query parameters for the CMS shop queue view."""
    return [
        ("act", "view"),
        ("object_id", str(settings.shop_id)),
        ("ver_id", str(settings.ver_id)),
        ("access", access_value(settings)),
        ("rnd", random_query_value()),
    ]


def start_product_import(
    session: requests.Session,
    settings: Settings,
    uploaded_file: UploadedFile,
    timeout: float = 30,
) -> requests.Response:
    """Submit an import job for a file already uploaded to the file manager."""
    access = access_value(settings)
    file_id = str(uploaded_file.file_id)
    query_params = [
        ("shop_id", str(settings.shop_id)),
        ("ver_id", str(settings.ver_id)),
        ("access", access),
        ("popup", "1"),
        ("rnd", random_query_value()),
        ("xhr", "1"),
        ("file_id", file_id),
        ("from_shop2_import", "1"),
        ("act", "queue"),
    ]
    form_data = [
        ("", ""),
        ("key_field", "article"),
        ("import_mode", "insert_or_update"),
        ("unmatched_mode", ""),
        ("folder_sep", "comma"),
        ("preserve_unset_val", "1"),
        ("file_id", file_id),
        ("mode", "queue"),
        ("access", access),
        ("ver_id", str(settings.ver_id)),
        ("xhr", "1"),
        ("rnd", random_query_value()),
    ]

    response = session.post(
        admin_url(settings, "shop2/import/products/"),
        params=query_params,
        data=form_data,
        timeout=timeout,
    )
    response.raise_for_status()
    logger.info("Submitted product import for admin file_id=%s", file_id)
    return response


def wait_for_import_completion(
    session: requests.Session,
    settings: Settings,
    baseline_cron_num: int,
    timeout: float = 30,
    wait_timeout: float = 900,
    poll_interval: float = 5,
) -> ImportQueueItem:
    """Wait until the newest task created after the baseline reports ``Готово``."""
    deadline = monotonic() + wait_timeout
    last_task: ImportQueueItem | None = None

    while True:
        response = session.get(
            admin_url(settings, "shop2/"),
            params=_shop_view_params(settings),
            timeout=timeout,
        )
        response.raise_for_status()
        task = newest_task_after(response.text, baseline_cron_num)

        if task is not None:
            last_task = task
            ensure_import_succeeded(task)
            if task.status.casefold() == "готово":
                logger.info("Import task #%s completed", task.cron_num)
                return task

        if monotonic() >= deadline:
            status = last_task.status if last_task else "not present in the queue"
            number = last_task.cron_num if last_task else "unknown"
            raise ImportQueueError(
                f"Import task #{number} did not reach 'Готово' within "
                f"{wait_timeout:g} seconds; last status: {status}"
            )

        sleep(poll_interval)


def delete_uploaded_file(
    session: requests.Session,
    settings: Settings,
    uploaded_file: UploadedFile,
    timeout: float = 30,
) -> None:
    """Remove the uploaded CSV from the admin file manager by its file ID."""
    response = session.get(
        admin_url(settings, "file/"),
        params=[
            ("act", "delete"),
            ("ver_id", str(settings.ver_id)),
            ("access", access_value(settings)),
            ("popup", "1"),
            ("object_id", str(uploaded_file.file_id)),
            ("rnd", random_query_value()),
            ("xhr", "1"),
        ],
        timeout=timeout,
    )
    response.raise_for_status()
    logger.info(
        "Deleted uploaded file %s (file_id=%s)",
        uploaded_file.filename,
        uploaded_file.file_id,
    )

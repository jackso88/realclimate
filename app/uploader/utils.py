"""URL, upload response, and queue HTML helpers for the uploader."""

import json
import secrets
from pathlib import Path
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from app.uploader.exceptions import ImportQueueError, UploadResponseError
from app.uploader.models import ImportQueueItem, Settings


def admin_url(settings: Settings, path: str) -> str:
    """Build an absolute CMS endpoint URL from the configured base URL.

    Args:
        settings: Uploader settings containing the CMS base URL.
        path: Absolute or relative path of the CMS endpoint.

    Returns:
        The joined endpoint URL, with duplicate boundary slashes normalized.
    """
    return urljoin(f"{settings.cms_url.rstrip('/')}/", path.lstrip("/"))


def access_value(settings: Settings) -> str:
    """Decode the configured URL-encoded CMS access token exactly once.

    Args:
        settings: Uploader settings containing the encoded access token.

    Returns:
        The access token decoded once for use as a request parameter.
    """
    return unquote(settings.access)


def random_query_value() -> str:
    """Generate a four-digit cache-busting request parameter.

    Returns:
        A decimal string from ``1000`` through ``9999``.
    """
    return str(secrets.randbelow(9000) + 1000)


def extract_uploaded_file_id(html: str, filename: str) -> str:
    """Find the CMS file ID matching an uploaded filename in the response HTML.

    Args:
        html: HTML returned by the CMS file upload endpoint.
        filename: Local filename submitted for upload. The full name and stem
            are both checked against the CMS file records.

    Returns:
        The matching file ID converted to a string.

    Raises:
        UploadResponseError: If no matching upload record contains a file ID.
    """
    soup = BeautifulSoup(html, "html.parser")
    requested_name = Path(filename).name
    requested_stem = Path(filename).stem

    for input_element in soup.select('input[name="file_json"][value]'):
        try:
            record = json.loads(input_element["value"])
        except (KeyError, json.JSONDecodeError):
            continue

        record_names = {record.get("filename"), record.get("name")}
        if requested_name not in record_names and requested_stem not in record_names:
            continue
        file_id = record.get("file_id")
        if file_id is not None:
            return str(file_id)

    raise UploadResponseError(
        f"Upload response did not contain file_id for {requested_name!r}"
    )


def parse_import_queue(html: str) -> list[ImportQueueItem]:
    """Parse numbered import tasks and status labels from shop view HTML.

    Args:
        html: HTML document returned by the CMS shop view endpoint.

    Returns:
        Queue items for rows containing both a numeric task number and a status.
        Rows with missing fields or malformed task numbers are skipped.
    """
    soup = BeautifulSoup(html, "html.parser")
    tasks: list[ImportQueueItem] = []

    for row in soup.select(".cron-list-item"):
        number_element = row.select_one(".cron-num")
        status_element = row.select_one(".cron-status")
        if number_element is None or status_element is None:
            continue

        number_text = number_element.get_text(strip=True).removeprefix("#")
        try:
            cron_num = int(number_text)
        except ValueError:
            continue

        status = " ".join(status_element.stripped_strings)
        tasks.append(ImportQueueItem(cron_num=cron_num, status=status))

    return tasks


def latest_cron_num(html: str) -> int:
    """Return the highest numeric task number present in the queue HTML.

    Args:
        html: HTML document returned by the CMS shop view endpoint.

    Returns:
        The largest parsed task number, or ``0`` when no valid tasks exist.
    """
    tasks = parse_import_queue(html)
    return max((task.cron_num for task in tasks), default=0)


def newest_task_after(html: str, baseline_cron_num: int) -> ImportQueueItem | None:
    """Find the highest-numbered task newer than a previously observed task.

    Args:
        html: HTML document returned by the CMS shop view endpoint.
        baseline_cron_num: Task number observed before the new import was queued.

    Returns:
        The queue item with the greatest number above the baseline, or ``None``
        if the HTML contains no newer valid task.
    """
    tasks = [
        task for task in parse_import_queue(html) if task.cron_num > baseline_cron_num
    ]
    if not tasks:
        return None
    return max(tasks, key=lambda task: task.cron_num)


def ensure_import_succeeded(task: ImportQueueItem) -> None:
    """Raise an error if an import task reports a failure status.

    Args:
        task: Parsed queue item whose status should be checked.

    Returns:
        ``None`` when the task status does not indicate failure.

    Raises:
        ImportQueueError: If the status contains a recognized failure marker.
    """
    lowered_status = task.status.casefold()
    if (
        "ошиб" in lowered_status
        or "error" in lowered_status
        or "failed" in lowered_status
    ):
        raise ImportQueueError(
            f"Import task #{task.cron_num} failed with status: {task.status}"
        )

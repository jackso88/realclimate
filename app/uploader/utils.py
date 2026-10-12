"""URL, upload response, and queue HTML helpers for the uploader."""

import json
from pathlib import Path
import secrets
from urllib.parse import unquote, urljoin

from bs4 import BeautifulSoup

from app.uploader.exceptions import ImportQueueError, UploadResponseError
from app.uploader.models import ImportQueueItem, Settings


def admin_url(settings: Settings, path: str) -> str:
    """Build a CMS endpoint URL using the configured CMS base URL."""
    return urljoin(f"{settings.cms_url.rstrip('/')}/", path.lstrip("/"))


def access_value(settings: Settings) -> str:
    """Decode an access token copied from an encoded browser URL once."""
    return unquote(settings.access)


def random_query_value() -> str:
    """Return a short cache-busting request parameter."""
    return str(secrets.randbelow(9000) + 1000)


def extract_uploaded_file_id(html: str, filename: str) -> str:
    """Find ``file_id`` for the uploaded file in ``file_json`` form inputs."""
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
    """Parse queue task numbers and status labels from the shop view HTML."""
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
    """Return the largest numeric queue task number, or zero for an empty list."""
    tasks = parse_import_queue(html)
    return max((task.cron_num for task in tasks), default=0)


def newest_task_after(html: str, baseline_cron_num: int) -> ImportQueueItem | None:
    """Return the newest queue item created after the supplied baseline."""
    tasks = [
        task for task in parse_import_queue(html) if task.cron_num > baseline_cron_num
    ]
    if not tasks:
        return None
    return max(tasks, key=lambda task: task.cron_num)


def ensure_import_succeeded(task: ImportQueueItem) -> None:
    """Raise when a queue task reports a terminal failure status."""
    lowered_status = task.status.casefold()
    if (
        "ошиб" in lowered_status
        or "error" in lowered_status
        or "failed" in lowered_status
    ):
        raise ImportQueueError(
            f"Import task #{task.cron_num} failed with status: {task.status}"
        )

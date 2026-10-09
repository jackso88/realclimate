"""Submit exports and manage their files in the admin queue."""

from io import BytesIO
import json
from pathlib import Path
import secrets
from time import monotonic, sleep
from urllib.parse import unquote, urljoin, urlparse
from zipfile import is_zipfile

import requests
from bs4 import BeautifulSoup

from app.downloader.current.config import Settings
from app.downloader.current.exceptions import (
    AdminFileNotFoundError,
    ExportArchiveError,
    ExportNotReadyError,
)
from app.downloader.current.models import DownloadedExport
from app.downloader.current.utils import DEFAULT_UPLOAD_DIR

EXTRA_FIELDS = (
    "vendor",
    "supplier",
    "image",
    "article",
    "code_1c",
    "folder",
    "hidden",
    "note",
    "body",
    "amount",
    "amount_min",
    "amount_multiplicity",
    "unit",
    "currency",
    "seo_noindex",
    "seo_title",
    "seo_description",
    "seo_keywords",
    "sef_url",
    "smt_title",
    "smt_description",
    "smt_image",
    "smt_type",
)


def _admin_url(settings: Settings, path: str) -> str:
    """Build an admin endpoint URL from the configured CMS base URL."""
    return urljoin(f"{settings.cms_url.rstrip('/')}/", path.lstrip("/"))


def _access_value(settings: Settings) -> str:
    """Accept either a raw access value or one copied from an encoded URL."""
    return unquote(settings.access)


def find_latest_export_archive(html: str, settings: Settings) -> tuple[int, str]:
    """Find the highest-numbered queue row with a ZIP link.

    Args:
        html: HTML returned by the shop page.
        settings: Settings used to resolve relative archive URLs.

    Returns:
        Numeric cron number and absolute archive URL.

    Raises:
        ExportNotReadyError: If no row has both a numeric cron number and a
            ZIP link.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []
    shop_url = _admin_url(settings, "shop2/")

    for row in soup.select(".cron-list-item"):
        cron_element = row.select_one(".cron-num")
        archive_link = row.select_one(".cron-link a[href]")
        if cron_element is None or archive_link is None:
            continue

        cron_text = cron_element.get_text(strip=True).removeprefix("#")
        try:
            cron_num = int(cron_text)
        except ValueError:
            continue

        href = archive_link.get("href", "")
        if not urlparse(href).path.lower().endswith(".zip"):
            continue
        candidates.append((cron_num, urljoin(shop_url, href)))

    if not candidates:
        raise ExportNotReadyError("No completed ZIP export was found in the queue")

    return max(candidates, key=lambda candidate: candidate[0])


def get_latest_export_cron_num(
    session: requests.Session,
    settings: Settings,
    timeout: float = 30,
) -> int:
    """Read the current highest completed export number before queueing a job.

    Returns zero when the file list contains no completed ZIP export. The CLI
    uses this snapshot so it will not accidentally download an older archive
    while the newly queued export is still running.
    """
    response = session.get(
        _admin_url(settings, "shop2/"),
        params=_shop_view_params(settings),
        timeout=timeout,
    )
    response.raise_for_status()
    try:
        cron_num, _ = find_latest_export_archive(response.text, settings)
    except ExportNotReadyError:
        return 0
    return cron_num


def _shop_view_params(settings: Settings) -> list[tuple[str, str]]:
    """Build query parameters for the shop view used by queue lookups."""
    return [
        ("act", "view"),
        ("object_id", str(settings.shop_id)),
        ("ver_id", str(settings.ver_id)),
        ("access", _access_value(settings)),
        ("rnd", str(secrets.randbelow(9000) + 1000)),
    ]


def start_product_export(
    session: requests.Session,
    settings: Settings,
    timeout: float = 30,
) -> requests.Response:
    """Submit a product CSV export request to the server-side queue.

    Args:
        session: Authenticated requests session.
        settings: CMS, shop, version, and access settings.
        timeout: Maximum time in seconds to wait for the response.

    Returns:
        The HTTP response returned after the export request is submitted.

    Raises:
        requests.HTTPError: If the endpoint returns an unsuccessful status.
        requests.RequestException: For connection and timeout errors.
    """
    access = _access_value(settings)
    query_params = [
        ("shop_id", str(settings.shop_id)),
        ("ver_id", str(settings.ver_id)),
        ("access", access),
        ("popup", "1"),
        ("rnd", str(secrets.randbelow(9000) + 1000)),
        ("xhr", "1"),
        ("mode", "queue"),
    ]
    form_data = [
        ("mode", "queue"),
        ("shop_id", str(settings.shop_id)),
        ("access", access),
        ("ver_id", str(settings.ver_id)),
        ("format", "csv"),
        ("folder_ids", ""),
        *(("extra_fields[]", field) for field in EXTRA_FIELDS),
        ("options[field_delim]", "semicolon"),
        ("options[values_delim]", "comma"),
        ("options[prices_delim]", "dot"),
        ("options[encoding]", "utf8-bom"),
        ("options[line_ending]", "lf"),
        ("options[ignore_hidden]", "-1"),
        ("options[fvs_key]", "name"),
        ("xhr", "1"),
        ("rnd", str(secrets.randbelow(9000) + 1000)),
    ]

    response = session.post(
        _admin_url(settings, "shop2/export/"),
        params=query_params,
        data=form_data,
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def download_latest_export(
    session: requests.Session,
    settings: Settings,
    upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
    timeout: float = 30,
    after_cron_num: int | None = None,
    wait_timeout: float = 300,
    poll_interval: float = 5,
) -> DownloadedExport:
    """Download the ZIP linked from the highest-numbered completed queue task.

    Args:
        session: Authenticated requests session.
        settings: Settings with CMS, shop, version, and access values.
        upload_dir: Local destination; defaults to ``storage/uploads``.
        timeout: Timeout in seconds for each HTTP request.
        after_cron_num: If provided, wait for an export with a larger queue
            number so an older completed file cannot be mistaken for this job.
        wait_timeout: Maximum seconds to wait for the newer export.
        poll_interval: Seconds between queue checks while waiting.

    Returns:
        A ``DownloadedExport`` containing the cron number, archive filename,
        URL, and local path. No metadata sidecar file is written.

    Raises:
        requests.HTTPError: If either HTTP request fails.
        ExportNotReadyError: If no completed ZIP is present in the queue.
        ExportArchiveError: If the linked response is not a valid ZIP file.
    """
    deadline = monotonic() + wait_timeout
    while True:
        queue_response = session.get(
            _admin_url(settings, "shop2/"),
            params=_shop_view_params(settings),
            timeout=timeout,
        )
        queue_response.raise_for_status()

        try:
            cron_num, archive_url = find_latest_export_archive(
                queue_response.text, settings
            )
        except ExportNotReadyError:
            if after_cron_num is None:
                raise
            cron_num = 0
            archive_url = ""

        if after_cron_num is None or cron_num > after_cron_num:
            break
        if monotonic() >= deadline:
            raise ExportNotReadyError(
                f"No completed export newer than cron #{after_cron_num} "
                f"appeared within {wait_timeout:g} seconds"
            )
        sleep(poll_interval)

    archive_response = session.get(archive_url, timeout=timeout)
    archive_response.raise_for_status()

    archive_bytes = archive_response.content
    if not is_zipfile(BytesIO(archive_bytes)):
        raise ExportArchiveError("The export link did not return a valid ZIP archive")

    archive_filename = Path(urlparse(archive_url).path).name
    if not archive_filename:
        raise ExportArchiveError("The ZIP download URL has no filename")

    destination = Path(upload_dir)
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / archive_filename
    temporary_archive = archive_path.with_name(archive_path.name + ".part")
    temporary_archive.write_bytes(archive_bytes)
    temporary_archive.replace(archive_path)

    return DownloadedExport(
        cron_num=cron_num,
        archive_filename=archive_filename,
        archive_path=archive_path,
        archive_url=archive_url,
    )


def delete_archive_from_admin(
    session: requests.Session,
    settings: Settings,
    archive_filename: str,
    timeout: float = 30,
) -> str:
    """Delete a named export archive from the admin file manager.

    The file manager returns file records in ``file_json`` hidden inputs. This
    function matches the requested filename, extracts its ``file_id``, and
    invokes the corresponding delete endpoint through the configured CMS URL.

    Args:
        session: Authenticated requests session.
        settings: CMS version and access settings.
        archive_filename: Exact archive filename to locate and delete.
        timeout: Timeout in seconds for each HTTP request.

    Returns:
        The deleted file's admin ``file_id``.

    Raises:
        requests.HTTPError: If the file listing or deletion request fails.
        AdminFileNotFoundError: If no file record matches ``archive_filename``.
    """
    access = _access_value(settings)
    file_url = _admin_url(settings, "file/")
    listing_params = [
        ("popup", "1"),
        ("selector", "1"),
        ("multiple", "false"),
        ("ver_id", str(settings.ver_id)),
        ("access", access),
        ("type_group_id", "0"),
        ("rnd", str(secrets.randbelow(9000) + 1000)),
        ("xhr", "1"),
    ]
    listing_response = session.get(file_url, params=listing_params, timeout=timeout)
    listing_response.raise_for_status()

    soup = BeautifulSoup(listing_response.text, "html.parser")
    file_id = None
    for file_json in soup.select('input[name="file_json"][value]'):
        try:
            record = json.loads(file_json["value"])
        except (KeyError, json.JSONDecodeError):
            continue

        record_names = {record.get("filename"), record.get("name")}
        if archive_filename in record_names:
            candidate_id = record.get("file_id")
            if candidate_id is not None:
                file_id = str(candidate_id)
                break

    if file_id is None:
        raise AdminFileNotFoundError(
            f"Archive {archive_filename!r} was not found in the admin file manager"
        )

    delete_params = [
        ("act", "delete"),
        ("ver_id", str(settings.ver_id)),
        ("access", access),
        ("popup", "1"),
        ("object_id", file_id),
        ("rnd", str(secrets.randbelow(9000) + 1000)),
        ("xhr", "1"),
    ]
    delete_response = session.get(file_url, params=delete_params, timeout=timeout)
    delete_response.raise_for_status()
    return file_id

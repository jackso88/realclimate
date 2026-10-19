"""Submit exports and manage their files in the admin queue."""

from io import BytesIO
import json
import logging
from pathlib import Path
import secrets
from time import monotonic, sleep
from urllib.parse import unquote, urljoin, urlparse
from zipfile import BadZipFile, ZipFile

import requests
from bs4 import BeautifulSoup

from app.downloader.current.config import Settings
from app.downloader.current.exceptions import (
    AdminFileNotFoundError,
    ExportArchiveError,
    ExportNotReadyError,
)
from app.downloader.current.models import DownloadedCsv

logger = logging.getLogger(__name__)

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
    """Build an absolute CMS URL for an endpoint path.

    Args:
        settings: CMS settings containing the base API URL.
        path: Relative endpoint path, with or without a leading slash.

    Returns:
        Absolute URL rooted at the configured CMS endpoint.
    """
    return urljoin(f"{settings.cms_url.rstrip('/')}/", path.lstrip("/"))


def _access_value(settings: Settings) -> str:
    """Normalize the access value, decoding URL-escaped input once.

    Args:
        settings: CMS settings containing the raw or URL-encoded access value.

    Returns:
        The decoded access value for use as an HTTP parameter.
    """
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


def find_latest_queue_cron_num(html: str) -> int:
    """Find the highest numeric cron number, including jobs still running.

    Args:
        html: HTML returned by the shop queue page.

    Returns:
        Highest cron number in the queue, or zero when no numeric queue
        entries are present.
    """
    soup = BeautifulSoup(html, "html.parser")
    cron_numbers: list[int] = []
    for cron_element in soup.select(".cron-list-item .cron-num"):
        cron_text = cron_element.get_text(strip=True).removeprefix("#")
        try:
            cron_numbers.append(int(cron_text))
        except ValueError:
            continue
    return max(cron_numbers, default=0)


def get_latest_export_cron_num(
    session: requests.Session,
    settings: Settings,
    timeout: float = 30,
) -> int:
    """Read the current highest queue number before queueing an export.

    Includes unfinished jobs, which do not have ZIP links yet. The CLI uses
    this snapshot so it will not mistake an older, still-running export for
    the newly queued job.

    Args:
        session: Authenticated CMS session used to fetch the shop view.
        settings: CMS URL, shop ID, version ID, and access settings.
        timeout: Maximum number of seconds to wait for the HTTP request.

    Returns:
        Highest numeric queue number, or zero if no queue entries are listed.

    Raises:
        requests.RequestException: If the CMS request fails.
    """
    response = session.get(
        _admin_url(settings, "shop2/"),
        params=_shop_view_params(settings),
        timeout=timeout,
    )
    response.raise_for_status()
    return find_latest_queue_cron_num(response.text)


def _shop_view_params(settings: Settings) -> list[tuple[str, str]]:
    """Build the query string used to retrieve the CMS shop queue.

    Args:
        settings: Shop, version, and access values for the CMS request.

    Returns:
        Ordered query parameter pairs, including a random cache buster.
    """
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
    logger.info("Export request accepted by the admin queue")
    return response


def download_latest_export_content(
    session: requests.Session,
    settings: Settings,
    after_cron_num: int,
    timeout: float = 30,
    wait_timeout: float = 300,
    poll_interval: float = 5,
) -> DownloadedCsv:
    """Wait for a newly queued export, download its ZIP, and extract the CSV.

    Args:
        session: Authenticated CMS session used for polling and downloading.
        settings: CMS URL, shop ID, version ID, and access settings.
        after_cron_num: Queue number observed before the export was submitted;
            only a newer export is accepted.
        timeout: Maximum wait for each individual HTTP request, in seconds.
        wait_timeout: Maximum total time to wait for a new export to finish.
        poll_interval: Delay between checks of the export queue, in seconds.

    Returns:
        CSV content and its source archive metadata as a ``DownloadedCsv``.

    Raises:
        requests.RequestException: If a CMS request fails.
        ExportNotReadyError: If no newer completed export appears in time.
        ExportArchiveError: If the ZIP is invalid or does not contain exactly
            one CSV file.
    """
    deadline = monotonic() + wait_timeout
    while True:
        response = session.get(
            _admin_url(settings, "shop2/"),
            params=_shop_view_params(settings),
            timeout=timeout,
        )
        response.raise_for_status()
        try:
            cron_num, archive_url = find_latest_export_archive(response.text, settings)
        except ExportNotReadyError:
            cron_num, archive_url = 0, ""

        if cron_num > after_cron_num:
            break
        if monotonic() >= deadline:
            raise ExportNotReadyError(
                f"No completed export newer than cron #{after_cron_num} appeared "
                f"within {wait_timeout:g} seconds"
            )
        sleep(poll_interval)

    archive_response = session.get(archive_url, timeout=timeout)
    archive_response.raise_for_status()
    archive_filename = Path(urlparse(archive_url).path).name
    if not archive_filename:
        raise ExportArchiveError("The ZIP download URL has no filename")
    try:
        with ZipFile(BytesIO(archive_response.content)) as archive:
            csv_members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".csv")
            ]
            if len(csv_members) != 1:
                raise ExportArchiveError(
                    f"Expected exactly one CSV in ZIP, found {len(csv_members)}"
                )
            csv_member = csv_members[0]
            content = archive.read(csv_member)
    except BadZipFile as error:
        raise ExportArchiveError("The export response was not a valid ZIP") from error

    logger.info("Downloaded export cron #%s into memory", cron_num)
    return DownloadedCsv(
        cron_num=cron_num,
        filename=Path(csv_member.filename).name,
        content=content,
        archive_filename=archive_filename,
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
    logger.info("Deleted admin archive %s (file_id=%s)", archive_filename, file_id)
    return file_id

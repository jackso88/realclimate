"""Submit, download, and unpack product exports from the admin queue."""

from dataclasses import dataclass
from io import BytesIO
import json
from pathlib import Path
import secrets
import shutil
from urllib.parse import unquote, urljoin, urlparse
from zipfile import BadZipFile, ZipFile, is_zipfile

import requests
from bs4 import BeautifulSoup

from app.downloader.current.config import Settings

# SHOP_URL = "https://realclimate.by/-/cms/v1/shop2/"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "storage" / "uploads"
EXPORT_METADATA_FILENAME = "latest_export.json"

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


class ExportNotReadyError(RuntimeError):
    """Raised when the admin queue page has no completed ZIP export."""


class ExportArchiveError(RuntimeError):
    """Raised when the downloaded archive is invalid or has no CSV file."""


@dataclass(frozen=True)
class DownloadedExport:
    """Metadata about a downloaded export, also persisted beside the archive.

    Attributes:
        cron_num: Numeric task number shown as ``#123456`` in the admin page.
        archive_url: URL from which the archive was downloaded.
        archive_path: Local path where the archive was saved.
        metadata_path: Local JSON file containing the task and archive details.
    """

    cron_num: int
    archive_url: str
    archive_path: Path
    metadata_path: Path


def find_latest_export_archive(html: str, settings: Settings) -> tuple[int, str]:
    """Return the highest-numbered queue task that links to a ZIP file.

    Args:
        html: HTML response from the shop page in the admin panel.
        settings: Settings with shop, version, and access values.

    Returns:
        A pair containing the numeric cron number and absolute ZIP URL.

    Raises:
        ExportNotReadyError: If no row contains both a numeric cron number and
            a ZIP download link.
    """
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for row in soup.select(".cron-list-item"):
        cron_element = row.select_one(".cron-num")
        archive_link = row.select_one('.cron-link a[href$=".zip"]')
        if cron_element is None or archive_link is None:
            continue

        cron_text = cron_element.get_text(strip=True)
        if cron_text.startswith("#"):
            cron_text = cron_text[1:]

        try:
            cron_num = int(cron_text)
        except ValueError:
            continue

        shop_url = f"{settings.cms_url}/shop2/"
        archive_url = urljoin(shop_url, archive_link["href"])
        candidates.append((cron_num, archive_url))

    if not candidates:
        raise ExportNotReadyError("No completed ZIP export was found in the queue")

    return max(candidates, key=lambda candidate: candidate[0])


def download_latest_export(
    session: requests.Session,
    settings: Settings,
    upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
    timeout: float = 30,
) -> DownloadedExport:
    """Find and download the latest available product export ZIP.

    The shop page is queried using ``shop_id`` as ``object_id``. The archive
    and a JSON record of its ``cron_num``, URL, and filename are saved to
    ``upload_dir``. Files are written via temporary paths and renamed only
    after a complete response has been received.

    Args:
        session: Authenticated 'requests' session.
        settings: Settings with shop, version, and access values.
        upload_dir: Destination directory; defaults to project storage/uploads.
        timeout: Timeout in seconds for each HTTP request.

    Returns:
        A record containing the selected queue number and local archive paths.

    Raises:
        requests.HTTPError: If the queue page or archive request fails.
        ExportNotReadyError: If the queue has no completed ZIP export.
        ExportArchiveError: If the linked response is not a valid ZIP archive.
    """
    queue_params = [
        ("act", "view"),
        ("object_id", str(settings.shop_id)),
        ("ver_id", str(settings.ver_id)),
        ("access", unquote(settings.access)),
        ("rnd", str(secrets.randbelow(9000) + 1000)),
    ]

    shop_url = f"{settings.cms_url}/shop2/"
    queue_response = session.get(shop_url, params=queue_params, timeout=timeout)
    queue_response.raise_for_status()

    cron_num, archive_url = find_latest_export_archive(queue_response.text, settings)
    archive_response = session.get(archive_url, timeout=timeout)
    archive_response.raise_for_status()

    archive_bytes = archive_response.content
    if not is_zipfile(BytesIO(archive_bytes)):
        raise ExportArchiveError("The export link did not return a valid ZIP archive")

    destination = Path(upload_dir)
    destination.mkdir(parents=True, exist_ok=True)
    archive_name = Path(urlparse(archive_url).path).name
    if not archive_name:
        raise ExportArchiveError("The ZIP download URL has no filename")

    archive_path = destination / archive_name
    temporary_archive = archive_path.with_name(archive_path.name + ".part")
    temporary_archive.write_bytes(archive_bytes)
    temporary_archive.replace(archive_path)

    metadata_path = destination / EXPORT_METADATA_FILENAME
    metadata = {
        "cron_num": cron_num,
        "archive_filename": archive_name,
        "archive_url": archive_url,
    }
    temporary_metadata = metadata_path.with_name(metadata_path.name + ".part")
    temporary_metadata.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_metadata.replace(metadata_path)

    return DownloadedExport(
        cron_num=cron_num,
        archive_url=archive_url,
        archive_path=archive_path,
        metadata_path=metadata_path,
    )


def extract_export_csv(
    archive_path: str | Path,
    upload_dir: str | Path = DEFAULT_UPLOAD_DIR,
) -> Path:
    """Extract the CSV member of a ZIP archive as ``current.csv``.

    The member is streamed directly into the destination file rather than
    extracted by its archive path, preventing ZIP path traversal. Exactly one
    CSV member is required to avoid silently selecting the wrong export.

    Args:
        archive_path: Path to a downloaded export ZIP archive.
        upload_dir: Destination directory; defaults to project storage/uploads.

    Returns:
        Path to the extracted ``current.csv`` file.

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


def start_product_export(
    session: requests.Session,
    settings: Settings,
    timeout: float = 30,
) -> requests.Response:
    """Submit a product CSV export request to the server-side queue.

    The request mirrors the admin form submission: URL query parameters are
    passed through ``params`` and the form body through ``data``. A list of
    key-value pairs preserves repeated ``extra_fields[]`` keys.

    Args:
        session: Authenticated session used for admin requests.
        settings: Application settings containing the shop, version, and access
            values required by the export endpoint.
        timeout: Maximum time in seconds to wait for the HTTP response.

    Returns:
        The HTTP response returned after the export task is submitted.

    Raises:
        requests.HTTPError: If the endpoint returns an unsuccessful status.
        requests.RequestException: If the request fails at the transport layer.
    """
    query_params = [
        ("shop_id", str(settings.shop_id)),
        ("ver_id", str(settings.ver_id)),
        ("access", settings.access),
        ("popup", "1"),
        ("rnd", "2153"),
        ("xhr", "1"),
        ("mode", "queue"),
    ]

    form_data = [
        ("mode", "queue"),
        ("shop_id", str(settings.shop_id)),
        ("access", settings.access),
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
        ("rnd", "1776"),
    ]

    export_url = f"{settings.cms_url}/shop2/export/"

    response = session.post(
        export_url,
        data=form_data,
        timeout=timeout,
        params=query_params,
    )
    response.raise_for_status()

    return response

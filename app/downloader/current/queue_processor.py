"""Submit product CSV exports to the admin site's background queue."""

import requests

from app.downloader.current.config import Settings

EXPORT_URL = "https://realclimate.by/-/cms/v1/shop2/export/"

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

    response = session.post(
        EXPORT_URL,
        params=query_params,
        data=form_data,
        timeout=timeout,
    )
    response.raise_for_status()

    return response

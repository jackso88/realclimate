"""Additional edge-case tests for CMS export polling, parsing and cleanup."""

import json
from io import BytesIO
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
import requests

from app.downloader.current import queue_processor
from app.downloader.current.config import Settings
from app.downloader.current.exceptions import (
    AdminFileNotFoundError,
    ExportArchiveError,
    ExportNotReadyError,
)
from app.downloader.current.queue_processor import (
    EXTRA_FIELDS,
    delete_archive_from_admin,
    download_latest_export_content,
    find_latest_export_archive,
    get_latest_export_cron_num,
    start_product_export,
)

SETTINGS = Settings(
    ver_id=21,
    access="u%3Btest",
    shop_id=11,
    cms_url="https://cms.example/-/cms/v1/",
)


def queue_row(number, href="/files/export.zip"):
    return (
        '<div class="cron-list-item">'
        f'<span class="cron-num">#{number}</span>'
        f'<span class="cron-link"><a href="{href}">file</a></span>'
        "</div>"
    )


def zip_bytes(files):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def response(text="", content=b"", error=None):
    reply = Mock(text=text, content=content)
    reply.raise_for_status = Mock(side_effect=error)
    return reply


@pytest.fixture
def no_sleep(monkeypatch):
    delays = []
    monkeypatch.setattr(queue_processor, "sleep", delays.append)
    return delays


def test_rows_without_a_number_or_link_are_skipped():
    html = (
        '<div class="cron-list-item"><span class="cron-num">#1</span></div>'
        '<div class="cron-list-item"><span class="cron-link">'
        '<a href="/a.zip">x</a></span></div>' + queue_row(5)
    )

    assert find_latest_export_archive(html, SETTINGS)[0] == 5


def test_rows_with_a_non_numeric_number_or_non_zip_link_are_skipped():
    html = (
        queue_row("abc")
        + queue_row(9, href="/files/export.csv")
        + queue_row(3, href="/files/export.zip")
    )

    assert find_latest_export_archive(html, SETTINGS)[0] == 3


def test_zip_links_with_query_strings_are_recognised():
    html = queue_row(4, href="/files/export.ZIP?download=1")

    number, url = find_latest_export_archive(html, SETTINGS)

    assert number == 4
    assert url == "https://cms.example/files/export.ZIP?download=1"


def test_latest_export_number_is_read_from_the_shop_view():
    session = Mock()
    session.get.return_value = response(queue_row(8) + queue_row(12))

    assert get_latest_export_cron_num(session, SETTINGS) == 12

    args, kwargs = session.get.call_args
    params = dict(kwargs["params"])
    assert args == ("https://cms.example/-/cms/v1/shop2/",)
    assert params["act"] == "view"
    assert params["object_id"] == "11"
    assert params["access"] == "u;test"


def test_latest_export_number_is_zero_without_a_finished_export():
    session = Mock()
    session.get.return_value = response("<html></html>")

    assert get_latest_export_cron_num(session, SETTINGS) == 0


def test_latest_export_number_propagates_http_errors():
    session = Mock()
    session.get.return_value = response(error=requests.HTTPError("503"))

    with pytest.raises(requests.HTTPError):
        get_latest_export_cron_num(session, SETTINGS)


def test_export_request_asks_for_a_semicolon_csv_including_hidden_items():
    session = Mock()
    session.post.return_value = response()

    start_product_export(session, SETTINGS)

    args, kwargs = session.post.call_args
    form = kwargs["data"]
    options = dict(pair for pair in form if pair[0].startswith("options["))
    assert args == ("https://cms.example/-/cms/v1/shop2/export/",)
    assert options["options[field_delim]"] == "semicolon"
    assert options["options[encoding]"] == "utf8-bom"
    assert options["options[ignore_hidden]"] == "-1"
    requested = [value for key, value in form if key == "extra_fields[]"]
    assert tuple(requested) == EXTRA_FIELDS


def test_export_request_propagates_http_errors():
    session = Mock()
    session.post.return_value = response(error=requests.HTTPError("500"))

    with pytest.raises(requests.HTTPError):
        start_product_export(session, SETTINGS)


def test_download_polls_until_a_newer_export_appears(no_sleep):
    archive = zip_bytes({"folder/export.csv": b"a;b\n"})
    session = Mock()
    session.get.side_effect = [
        response(queue_row(5)),
        response("<html></html>"),
        response(queue_row(5) + queue_row(6)),
        response(content=archive),
    ]

    downloaded = download_latest_export_content(session, SETTINGS, after_cron_num=5)

    assert downloaded.cron_num == 6
    assert downloaded.filename == "export.csv"
    assert downloaded.archive_filename == "export.zip"
    assert downloaded.content == b"a;b\n"
    assert no_sleep == [5, 5]


def test_download_times_out_when_no_newer_export_appears(monkeypatch, no_sleep):
    clock = iter([0, 10_000])
    monkeypatch.setattr(queue_processor, "monotonic", lambda: next(clock))
    session = Mock()
    session.get.return_value = response(queue_row(5))

    with pytest.raises(ExportNotReadyError, match="cron #5"):
        download_latest_export_content(
            session, SETTINGS, after_cron_num=5, wait_timeout=30
        )


def test_download_rejects_a_response_that_is_not_a_zip(no_sleep):
    session = Mock()
    session.get.side_effect = [response(queue_row(6)), response(content=b"<html>")]

    with pytest.raises(ExportArchiveError, match="not a valid ZIP"):
        download_latest_export_content(session, SETTINGS, after_cron_num=5)


def test_download_rejects_a_zip_with_several_csv_files(no_sleep):
    archive = zip_bytes({"a.csv": b"1", "b.csv": b"2"})
    session = Mock()
    session.get.side_effect = [response(queue_row(6)), response(content=archive)]

    with pytest.raises(ExportArchiveError, match="found 2"):
        download_latest_export_content(session, SETTINGS, after_cron_num=5)


def file_listing(*records, raw=""):
    inputs = "".join(
        f"<input name='file_json' value='{json.dumps(record)}'>" for record in records
    )
    return response(f"<html>{raw}{inputs}</html>")


def test_delete_matches_the_archive_by_filename_and_removes_it():
    other = {"file_id": 1, "filename": "other.zip"}
    wanted = {"file_id": 2, "name": "x.zip"}
    session = Mock()
    session.get.side_effect = [file_listing(other, wanted), response()]

    file_id = delete_archive_from_admin(session, SETTINGS, "x.zip")

    assert file_id == "2"
    delete_call = session.get.call_args_list[1]
    params = dict(delete_call.kwargs["params"])
    assert params["act"] == "delete"
    assert params["object_id"] == "2"
    assert params["access"] == "u;test"


def test_delete_skips_unreadable_and_id_less_records():
    broken = "<input name='file_json' value='{broken'>"
    without_id = {"filename": "x.zip"}
    with_id = {"file_id": 8, "filename": "x.zip"}
    session = Mock()
    session.get.side_effect = [
        file_listing(without_id, with_id, raw=broken),
        response(),
    ]

    assert delete_archive_from_admin(session, SETTINGS, "x.zip") == "8"


def test_delete_fails_when_the_archive_is_not_listed():
    session = Mock()
    session.get.return_value = file_listing({"file_id": 1, "filename": "other.zip"})

    with pytest.raises(AdminFileNotFoundError, match="x.zip"):
        delete_archive_from_admin(session, SETTINGS, "x.zip")

    assert session.get.call_count == 1


def test_delete_propagates_http_errors_from_the_listing():
    session = Mock()
    session.get.return_value = response(error=requests.HTTPError("403"))

    with pytest.raises(requests.HTTPError):
        delete_archive_from_admin(session, SETTINGS, "x.zip")

"""Tests for CMS upload, import submission and queue polling."""

import json

import pytest
import requests

from app.uploader import queue_processor
from app.uploader.exceptions import (
    ImportQueueError,
    UploadFileError,
    UploadResponseError,
)
from app.uploader.models import ImportQueueItem, Settings, UploadedFile
from app.uploader.queue_processor import (
    delete_uploaded_file,
    get_latest_import_cron_num,
    start_product_import,
    upload_processed_content,
    wait_for_import_completion,
)

SETTINGS = Settings(
    ver_id=1,
    access="u%3B123",
    shop_id=5,
    cms_url="https://cms.example/-/cms/v1",
)


class FakeResponse:
    """Minimal HTTP response with a controllable status check."""

    def __init__(self, text="", error=None):
        self.text = text
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error


class FakeSession:
    """Return queued responses and remember every request."""

    def __init__(self, gets=(), posts=()):
        self.gets = list(gets)
        self.posts = list(posts)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.gets.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self.posts.pop(0)


def upload_response(file_id="99", filename="processed.csv"):
    record = {"file_id": file_id, "filename": filename, "name": filename[:-4]}
    return FakeResponse(f"<input name='file_json' value='{json.dumps(record)}'>")


def queue_page(*tasks):
    rows = "".join(
        '<div class="cron-list-item">'
        f'<span class="cron-num">#{number}</span>'
        f'<span class="cron-status">{status}</span>'
        "</div>"
        for number, status in tasks
    )
    return FakeResponse(f"<html>{rows}</html>")


@pytest.fixture
def no_sleep(monkeypatch):
    """Skip real waiting between polls and record the requested delays."""
    delays = []
    monkeypatch.setattr(queue_processor, "sleep", delays.append)
    return delays


def test_upload_rejects_content_above_the_cms_limit(monkeypatch):
    monkeypatch.setattr(queue_processor, "MAX_UPLOAD_SIZE", 10)
    session = FakeSession()

    with pytest.raises(UploadFileError, match="upload limit"):
        upload_processed_content(session, SETTINGS, b"x" * 11)

    assert session.calls == []


def test_upload_posts_the_file_and_returns_its_cms_identifier():
    session = FakeSession(posts=[upload_response("99", "data.csv")])

    uploaded = upload_processed_content(session, SETTINGS, b"a,b\n1,2\n", "data.csv")

    assert uploaded == UploadedFile(file_id="99", filename="data.csv")
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("post", "https://cms.example/-/cms/v1/file/")
    assert kwargs["timeout"] == 60


def test_upload_sends_decoded_access_and_form_fields():
    session = FakeSession(posts=[upload_response("99", "data.csv")])

    upload_processed_content(session, SETTINGS, b"a,b\n", "data.csv")

    kwargs = session.calls[0][2]
    params = dict(kwargs["params"])
    form = dict(kwargs["data"])
    assert params["act"] == "edit"
    assert params["access"] == "u;123"
    assert params["ver_id"] == "1"
    assert params["time"].isdigit()
    assert form["names"] == "data"
    assert form["MAX_FILE_SIZE"] == str(queue_processor.MAX_UPLOAD_SIZE)
    name, handle, content_type = kwargs["files"]["files"]
    assert (name, content_type) == ("data.csv", "text/csv")
    assert handle.getvalue() == b"a,b\n"


def test_upload_propagates_http_errors_without_parsing_the_reply():
    error = requests.HTTPError("502 Bad Gateway")
    session = FakeSession(posts=[FakeResponse("<html></html>", error=error)])

    with pytest.raises(requests.HTTPError):
        upload_processed_content(session, SETTINGS, b"data")


def test_upload_fails_when_the_reply_does_not_describe_the_file():
    session = FakeSession(posts=[FakeResponse("<html>uploaded</html>")])

    with pytest.raises(UploadResponseError):
        upload_processed_content(session, SETTINGS, b"data")


def test_latest_import_number_comes_from_the_shop_queue_view():
    session = FakeSession(gets=[queue_page((3, "Готово"), (12, "Готово"))])

    assert get_latest_import_cron_num(session, SETTINGS) == 12

    _, url, kwargs = session.calls[0]
    params = dict(kwargs["params"])
    assert url == "https://cms.example/-/cms/v1/shop2/"
    assert params["act"] == "view"
    assert params["object_id"] == "5"
    assert params["access"] == "u;123"


def test_latest_import_number_is_zero_for_an_empty_queue():
    session = FakeSession(gets=[queue_page()])

    assert get_latest_import_cron_num(session, SETTINGS) == 0


def test_latest_import_number_propagates_http_errors():
    error = requests.ConnectionError("down")
    session = FakeSession(gets=[FakeResponse(error=error)])

    with pytest.raises(requests.ConnectionError):
        get_latest_import_cron_num(session, SETTINGS)


def test_start_import_queues_an_insert_or_update_keyed_by_article():
    response = FakeResponse()
    session = FakeSession(posts=[response])
    uploaded = UploadedFile(file_id="99", filename="processed.csv")

    result = start_product_import(session, SETTINGS, uploaded)

    assert result is response
    _, url, kwargs = session.calls[0]
    form = dict(kwargs["data"])
    params = dict(kwargs["params"])
    assert url == "https://cms.example/-/cms/v1/shop2/import/products/"
    assert params["act"] == "queue"
    assert params["file_id"] == "99"
    assert form["key_field"] == "article"
    assert form["import_mode"] == "insert_or_update"
    assert form["mode"] == "queue"
    assert form["file_id"] == "99"
    assert form["preserve_unset_val"] == "1"


def test_start_import_propagates_http_errors():
    error = requests.HTTPError("500")
    session = FakeSession(posts=[FakeResponse(error=error)])

    with pytest.raises(requests.HTTPError):
        start_product_import(session, SETTINGS, UploadedFile("99", "processed.csv"))


def test_wait_returns_the_new_task_once_it_is_done(no_sleep):
    session = FakeSession(
        gets=[
            queue_page((5, "Готово")),
            queue_page((5, "Готово"), (6, "Выполняется")),
            queue_page((5, "Готово"), (6, "Готово")),
        ]
    )

    task = wait_for_import_completion(session, SETTINGS, baseline_cron_num=5)

    assert task == ImportQueueItem(6, "Готово")
    assert len(session.calls) == 3
    assert no_sleep == [5, 5]


def test_wait_ignores_tasks_that_existed_before_submission(no_sleep):
    session = FakeSession(gets=[queue_page((5, "Готово")), queue_page((6, "Готово"))])

    task = wait_for_import_completion(session, SETTINGS, baseline_cron_num=5)

    assert task.cron_num == 6


def test_wait_stops_immediately_when_the_import_fails(no_sleep):
    session = FakeSession(gets=[queue_page((6, "Ошибка импорта"))])

    with pytest.raises(ImportQueueError, match="#6"):
        wait_for_import_completion(session, SETTINGS, baseline_cron_num=5)

    assert len(session.calls) == 1
    assert no_sleep == []


def test_wait_times_out_and_reports_the_last_status(monkeypatch, no_sleep):
    clock = iter([0, 10_000])
    monkeypatch.setattr(queue_processor, "monotonic", lambda: next(clock))
    session = FakeSession(gets=[queue_page((6, "Выполняется"))])

    with pytest.raises(ImportQueueError) as error:
        wait_for_import_completion(
            session, SETTINGS, baseline_cron_num=5, wait_timeout=30
        )

    assert "#6" in str(error.value)
    assert "Выполняется" in str(error.value)
    assert "30 seconds" in str(error.value)


def test_wait_times_out_when_the_task_never_appears(monkeypatch, no_sleep):
    clock = iter([0, 10_000])
    monkeypatch.setattr(queue_processor, "monotonic", lambda: next(clock))
    session = FakeSession(gets=[queue_page((5, "Готово"))])

    with pytest.raises(ImportQueueError) as error:
        wait_for_import_completion(
            session, SETTINGS, baseline_cron_num=5, wait_timeout=30
        )

    assert "#unknown" in str(error.value)
    assert "not present in the queue" in str(error.value)


def test_delete_removes_the_file_by_its_identifier():
    session = FakeSession(gets=[FakeResponse()])

    delete_uploaded_file(session, SETTINGS, UploadedFile("99", "processed.csv"))

    _, url, kwargs = session.calls[0]
    params = dict(kwargs["params"])
    assert url == "https://cms.example/-/cms/v1/file/"
    assert params["act"] == "delete"
    assert params["object_id"] == "99"
    assert params["access"] == "u;123"


def test_delete_propagates_http_errors():
    error = requests.HTTPError("404")
    session = FakeSession(gets=[FakeResponse(error=error)])

    with pytest.raises(requests.HTTPError):
        delete_uploaded_file(session, SETTINGS, UploadedFile("99", "processed.csv"))

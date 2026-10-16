"""Tests for the uploader's URL, upload-response and queue-HTML helpers."""

import json

import pytest

from app.uploader import utils
from app.uploader.exceptions import ImportQueueError, UploadResponseError
from app.uploader.models import ImportQueueItem, Settings
from app.uploader.utils import (
    access_value,
    admin_url,
    ensure_import_succeeded,
    extract_uploaded_file_id,
    latest_cron_num,
    newest_task_after,
    parse_import_queue,
    random_query_value,
)


def make_settings(**overrides):
    values = {
        "ver_id": 1,
        "access": "u%3B123",
        "shop_id": 5,
        "cms_url": "https://cms.example/-/cms/v1",
    }
    values.update(overrides)
    return Settings(**values)


def file_input(**record):
    """Render the hidden input the CMS uses to describe an uploaded file."""
    return f"<input name='file_json' value='{json.dumps(record)}'>"


def queue_row(number, status):
    """Render one row of the CMS import queue."""
    return (
        '<div class="cron-list-item">'
        f'<span class="cron-num">#{number}</span>'
        f'<span class="cron-status">{status}</span>'
        "</div>"
    )


def test_admin_url_joins_the_endpoint_to_the_base_url():
    url = admin_url(make_settings(), "file/")

    assert url == "https://cms.example/-/cms/v1/file/"


def test_admin_url_normalizes_slashes_at_the_boundary():
    settings = make_settings(cms_url="https://cms.example/-/cms/v1/")

    assert admin_url(settings, "/shop2/") == "https://cms.example/-/cms/v1/shop2/"


def test_access_value_is_decoded_exactly_once():
    assert access_value(make_settings(access="u%3B123")) == "u;123"
    assert access_value(make_settings(access="u%253B123")) == "u%3B123"


@pytest.mark.parametrize(("raw", "expected"), [(0, "1000"), (8999, "9999")])
def test_random_query_value_spans_four_digits(monkeypatch, raw, expected):
    requested = []

    def fake_randbelow(limit):
        requested.append(limit)
        return raw

    monkeypatch.setattr(utils.secrets, "randbelow", fake_randbelow)

    assert random_query_value() == expected
    assert requested == [9000]


def test_extract_uploaded_file_id_matches_the_filename():
    html = file_input(file_id=77, filename="processed.csv", name="processed")

    assert extract_uploaded_file_id(html, "processed.csv") == "77"


def test_extract_uploaded_file_id_also_matches_the_name_without_extension():
    html = file_input(file_id="88", name="processed")

    assert extract_uploaded_file_id(html, "processed.csv") == "88"


def test_extract_uploaded_file_id_picks_the_matching_record():
    html = file_input(file_id=1, filename="other.csv") + file_input(
        file_id=2, filename="processed.csv"
    )

    assert extract_uploaded_file_id(html, "processed.csv") == "2"


def test_extract_uploaded_file_id_ignores_unreadable_records():
    html = "<input name='file_json' value='{broken'>" + file_input(
        file_id=5, filename="processed.csv"
    )

    assert extract_uploaded_file_id(html, "processed.csv") == "5"


def test_extract_uploaded_file_id_skips_records_without_an_id():
    html = file_input(filename="processed.csv") + file_input(
        file_id=9, filename="processed.csv"
    )

    assert extract_uploaded_file_id(html, "processed.csv") == "9"


def test_extract_uploaded_file_id_fails_when_nothing_matches():
    html = file_input(file_id=1, filename="other.csv")

    with pytest.raises(UploadResponseError, match="processed.csv"):
        extract_uploaded_file_id(html, "processed.csv")


def test_parse_import_queue_reads_numbers_and_statuses():
    html = queue_row(7, "Готово") + queue_row(8, "Выполняется")

    assert parse_import_queue(html) == [
        ImportQueueItem(7, "Готово"),
        ImportQueueItem(8, "Выполняется"),
    ]


def test_parse_import_queue_accepts_numbers_without_a_hash_prefix():
    html = queue_row(7, "Готово").replace("#7", "7")

    assert parse_import_queue(html) == [ImportQueueItem(7, "Готово")]


def test_parse_import_queue_joins_status_fragments_from_nested_elements():
    html = queue_row(3, "<b>Ожидает</b>\n   <i>запуска</i>")

    assert parse_import_queue(html)[0].status == "Ожидает запуска"


def test_parse_import_queue_skips_incomplete_and_malformed_rows():
    html = (
        '<div class="cron-list-item"><span class="cron-num">#1</span></div>'
        '<div class="cron-list-item"><span class="cron-status">Готово</span></div>'
        + queue_row("abc", "Готово")
        + queue_row(4, "Готово")
    )

    assert parse_import_queue(html) == [ImportQueueItem(4, "Готово")]


def test_latest_cron_num_is_the_highest_number():
    html = queue_row(3, "Готово") + queue_row(11, "Готово") + queue_row(9, "Готово")

    assert latest_cron_num(html) == 11


def test_latest_cron_num_is_zero_for_an_empty_queue():
    assert latest_cron_num("<html></html>") == 0


def test_newest_task_after_returns_the_highest_newer_task():
    html = queue_row(5, "Готово") + queue_row(8, "Выполняется") + queue_row(7, "Ждёт")

    assert newest_task_after(html, 5) == ImportQueueItem(8, "Выполняется")


def test_newest_task_after_ignores_tasks_at_or_below_the_baseline():
    html = queue_row(4, "Готово") + queue_row(5, "Готово")

    assert newest_task_after(html, 5) is None


@pytest.mark.parametrize(
    "status", ["Ошибка", "ОШИБКА импорта", "Error", "task FAILED", "Failed"]
)
def test_failure_statuses_raise(status):
    with pytest.raises(ImportQueueError, match="#7"):
        ensure_import_succeeded(ImportQueueItem(7, status))


@pytest.mark.parametrize("status", ["Готово", "В очереди", "Выполняется", ""])
def test_non_failure_statuses_pass(status):
    ensure_import_succeeded(ImportQueueItem(7, status))

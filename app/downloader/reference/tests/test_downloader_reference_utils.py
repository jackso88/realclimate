"""Tests for in-memory serialization of Google Sheets data."""

from app.downloader.reference.utils import serialize_data_to_csv


def test_serializes_rows_to_csv_bytes():
    assert serialize_data_to_csv([["name", "price"], ["A, B", "12"]]) == (
        b'name,price\r\n"A, B",12\r\n'
    )

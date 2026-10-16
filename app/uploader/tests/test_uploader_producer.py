"""Tests for the uploader request helper used by other services."""

from unittest.mock import Mock

from app.messaging.payloads import decode_bytes
from app.messaging.topics import UPLOADER_REQUESTS
from app.uploader.producer import request_import


def test_request_import_sends_the_compressed_csv_to_the_uploader():
    bus = Mock()

    result = request_import(bus, "responses", "group", b"a,b\n1,2\n")

    assert result is bus.request.return_value
    args = bus.request.call_args
    assert args.args[:3] == (UPLOADER_REQUESTS, "responses", "import_processed_csv")
    payload = args.args[3]
    assert payload["filename"] == "processed.csv"
    assert decode_bytes(payload["csv_gzip_base64"]) == b"a,b\n1,2\n"
    assert args.kwargs == {"timeout": 1200, "response_group": "group"}


def test_request_import_accepts_a_custom_filename_and_timeout():
    bus = Mock()

    request_import(bus, "responses", "group", b"x", filename="a.csv", timeout=5)

    payload = bus.request.call_args.args[3]
    assert payload["filename"] == "a.csv"
    assert bus.request.call_args.kwargs["timeout"] == 5

"""Tests that the uploader sends provided bytes without local file I/O."""

from unittest.mock import Mock

from app.uploader.models import Settings, UploadedFile
from app.uploader.queue_processor import (
    delete_uploaded_file,
    start_product_import,
    upload_processed_content,
)


def test_upload_processed_content_sends_multipart_bytes():
    settings = Settings(
        ver_id=1,
        access="test-access",
        shop_id=2,
        cms_url="https://example.test/-/cms/v1",
    )
    session = Mock()
    response = Mock()
    response.text = '<input name="file_json" value=\'{"file_id":"77","name":"processed","filename":"processed.csv"}\'>'
    response.status_code = 200
    session.post.return_value = response

    uploaded = upload_processed_content(
        session, settings, b"article,price\nSKU,1\n", "processed.csv"
    )

    assert uploaded.file_id == "77"
    call = session.post.call_args
    assert call.kwargs["files"]["files"][1].getvalue() == b"article,price\nSKU,1\n"


def test_import_request_uses_uploaded_file_reference():
    settings = Settings(
        ver_id=1,
        access="test-access",
        shop_id=2,
        cms_url="https://example.test/-/cms/v1",
    )
    session = Mock()
    response = Mock()
    session.post.return_value = response
    uploaded = UploadedFile(file_id="test-file-id", filename="processed.csv")

    assert start_product_import(session, settings, uploaded) is response
    assert ("file_id", "test-file-id") in session.post.call_args.kwargs["data"]


def test_uploaded_admin_file_is_deleted_by_its_identifier():
    settings = Settings(
        ver_id=1,
        access="test-access",
        shop_id=2,
        cms_url="https://example.test/-/cms/v1",
    )
    session = Mock()
    session.get.return_value = Mock()
    uploaded = UploadedFile(file_id="test-file-id", filename="processed.csv")

    delete_uploaded_file(session, settings, uploaded)

    assert ("object_id", "test-file-id") in session.get.call_args.kwargs["params"]

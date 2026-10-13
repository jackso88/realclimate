"""Tests for the reference downloader Kafka contract."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.downloader.reference import consumer
from app.messaging.models import Envelope


def test_reference_handler_serializes_and_replies_with_csv(monkeypatch):
    settings = SimpleNamespace(
        spreadsheet_url="sheet-url",
        sheet_name="Products",
        credentials_file="credentials.json",
        token_file="token.json",
    )
    credentials = object()
    worksheet = Mock()
    worksheet.get_all_values.return_value = [["name"], ["Item A"]]
    client = Mock()
    client.open_by_key.return_value.worksheet.return_value = worksheet
    authorize = Mock(return_value=client)
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "extract_spreadsheet_id", lambda _: "fake-sheet-id")
    monkeypatch.setattr(consumer, "get_credentials", Mock(return_value=credentials))
    monkeypatch.setattr(consumer.gspread, "authorize", authorize)
    monkeypatch.setattr(
        consumer, "serialize_data_to_csv", lambda rows: b"name\nItem A\n"
    )
    publish = Mock()
    failure = Mock()
    monkeypatch.setattr(consumer, "publish_reference_csv", publish)
    monkeypatch.setattr(consumer, "publish_reply", failure)
    request = Envelope.create("download_csv", {}, reply_to="response")
    bus = object()

    consumer.handle_request(request, bus)

    authorize.assert_called_once_with(credentials)
    client.open_by_key.assert_called_once_with("fake-sheet-id")
    worksheet.get_all_values.assert_called_once_with()
    publish.assert_called_once_with(bus, request, b"name\nItem A\n")
    failure.assert_not_called()

"""Focused tests for the reference downloader's pub/sub consumer contract."""

from types import SimpleNamespace
from unittest.mock import Mock

from app.contracts.models import Envelope
from app.downloader.reference import consumer


def test_reference_sync_publishes_changed_csv_with_pipeline_correlation(monkeypatch):
    settings = SimpleNamespace(
        spreadsheet_url="https://docs.google.com/spreadsheets/d/fake-sheet/edit",
        sheet_name="Products",
        credentials_file="credentials.json",
        token_file="token.json",
        auth_mode="user",
    )
    worksheet = Mock()
    worksheet.get_all_values.return_value = [["name"], ["Item A"]]
    spreadsheet = Mock()
    spreadsheet.worksheet.return_value = worksheet
    client = Mock()
    client.open_by_key.return_value = spreadsheet
    authorize = Mock(return_value=client)
    publish = Mock(return_value=True)
    failure = Mock()
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "extract_spreadsheet_id", lambda _: "fake-sheet-id")
    monkeypatch.setattr(consumer, "get_credentials", Mock(return_value="credentials"))
    monkeypatch.setattr(consumer.gspread, "authorize", authorize)
    monkeypatch.setattr(consumer, "serialize_data_to_csv", lambda _: b"name\nItem A\n")
    monkeypatch.setattr(consumer, "publish_reference_if_changed", publish)
    monkeypatch.setattr(consumer, "publish_failure", failure)
    message = Envelope.create("sync_reference", {}, correlation_id="pipeline-123")
    bus = object()

    consumer.handle_request(message, bus)

    client.open_by_key.assert_called_once_with("fake-sheet-id")
    spreadsheet.worksheet.assert_called_once_with("Products")
    worksheet.get_all_values.assert_called_once_with()
    publish.assert_called_once_with(bus, message, b"name\nItem A\n")
    failure.assert_not_called()

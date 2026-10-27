"""Fixtures for the reference downloader consumer tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SETTINGS = SimpleNamespace(
    spreadsheet_url="https://docs.google.com/spreadsheets/d/SHEET123/edit",
    sheet_name="1. Для заливки",
    credentials_file="credentials.json",
    token_file="token.json",
    bootstrap_servers="localhost:9092",
)


@pytest.fixture
def reference_sheet(monkeypatch):
    """Mock the Google client chain and the reply helpers used by the handler."""
    from app.downloader.reference import consumer

    parts = SimpleNamespace(
        worksheet=Mock(),
        spreadsheet=Mock(),
        client=Mock(),
        failure=Mock(),
        publish=Mock(return_value=True),
        checkpoint=Mock(),
        credentials=Mock(return_value="credentials"),
    )
    parts.worksheet.get_all_values.return_value = [["код", "модель"], ["НС-1", "A"]]
    parts.spreadsheet.worksheet.return_value = parts.worksheet
    parts.client.open_by_key.return_value = parts.spreadsheet
    monkeypatch.setattr(consumer, "load_settings", lambda: SETTINGS)
    monkeypatch.setattr(consumer, "get_credentials", parts.credentials)
    monkeypatch.setattr(consumer.gspread, "authorize", Mock(return_value=parts.client))
    monkeypatch.setattr(consumer, "publish_failure", parts.failure)
    monkeypatch.setattr(consumer, "publish_reference_if_changed", parts.publish)
    monkeypatch.setattr(consumer, "checkpoint_completed_reference", parts.checkpoint)
    return parts

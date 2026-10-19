"""Tests for Telegram notification filtering."""

from unittest.mock import patch

from app.contracts.models import Envelope
from app.notifications.consumer import handle_notification


@patch("app.notifications.consumer.send_telegram_message")
def test_empty_change_reports_are_ignored(send):
    handle_notification(Envelope.create("detailed_changes", {"changes": []}), None)
    send.assert_not_called()


@patch("app.notifications.consumer.send_telegram_message")
def test_failures_are_forwarded(send):
    handle_notification(
        Envelope.create("failure", {"service": "test", "error": "oops"}), None
    )
    send.assert_called_once()
    assert "oops" in send.call_args.args[0]

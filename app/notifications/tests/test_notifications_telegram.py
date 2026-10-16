"""Tests for the Telegram Bot API client."""

from unittest.mock import Mock

import pytest
import requests

from app.notifications import telegram


@pytest.fixture
def post(monkeypatch):
    """Replace requests.post with a mock that returns an accepted response."""
    response = Mock()
    response.json.return_value = {"ok": True}
    mock_post = Mock(return_value=response)
    monkeypatch.setattr(telegram.requests, "post", mock_post)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    mock_post.response = response
    return mock_post


def test_message_is_posted_to_the_bot_endpoint(post):
    telegram.send_telegram_message("hello")

    post.assert_called_once_with(
        "https://api.telegram.org/bot123:abc/sendMessage",
        json={"chat_id": "42", "text": "hello"},
        timeout=15,
    )


def test_timeout_can_be_customised(post):
    telegram.send_telegram_message("hello", timeout=3)

    assert post.call_args.kwargs["timeout"] == 3


def test_missing_bot_token_is_reported_by_name(post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")

    with pytest.raises(KeyError, match="TELEGRAM_BOT_TOKEN"):
        telegram.send_telegram_message("hello")

    post.assert_not_called()


def test_missing_chat_id_is_reported_by_name(post, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID")

    with pytest.raises(KeyError, match="TELEGRAM_CHAT_ID"):
        telegram.send_telegram_message("hello")

    post.assert_not_called()


def test_http_errors_propagate(post):
    post.response.raise_for_status.side_effect = requests.HTTPError("400 Bad Request")

    with pytest.raises(requests.HTTPError):
        telegram.send_telegram_message("hello")


def test_network_errors_propagate(post):
    post.side_effect = requests.ConnectionError("no route")

    with pytest.raises(requests.ConnectionError):
        telegram.send_telegram_message("hello")


def test_a_rejected_notification_raises(post):
    post.response.json.return_value = {"ok": False, "description": "chat not found"}

    with pytest.raises(RuntimeError, match="rejected"):
        telegram.send_telegram_message("hello")

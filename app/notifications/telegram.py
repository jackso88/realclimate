"""Telegram Bot API client for operator notifications."""

import os

import requests


def send_telegram_message(text: str, timeout: float = 15) -> None:
    """Send a message to the chat configured for the administrator.

    Args:
        text: Plain-text notification to send.
        timeout: Maximum time to wait for the Telegram API, in seconds.

    Raises:
        requests.RequestException: If the HTTP request fails or times out.
        RuntimeError: If Telegram returns a response with ``ok`` set to false.
        KeyError: If the bot token or chat ID is not configured.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=timeout,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram rejected the notification")

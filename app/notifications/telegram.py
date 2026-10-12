"""Telegram Bot API client for operator notifications."""

import os

import requests


def send_telegram_message(text: str, timeout: float = 15) -> None:
    """Send a message to the configured administrator chat."""
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

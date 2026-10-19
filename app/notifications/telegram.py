"""Telegram Bot API client for operator notifications."""

import os
import time

import requests

from app.messaging.kafka import sanitize_error
from app.notifications.exceptions import TelegramDeliveryError

# Telegram rejects messages longer than 4096 characters. Parts are cut a little
# below that so a "[2/5]" header and characters Telegram counts as two (for
# example emoji) can never push a part over the real limit.
TELEGRAM_MESSAGE_LIMIT = 4096
PART_LIMIT = 4000
# Telegram allows roughly one message per second to the same chat.
PAUSE_BETWEEN_PARTS_SECONDS = 1.0


def _split_long_line(line: str, limit: int) -> list[str]:
    """Cut one over-long line into pieces, preferring natural boundaries.

    Args:
        line: A single line without newlines.
        limit: Maximum length of each returned piece.

    Returns:
        The line itself when it fits; otherwise pieces cut after a comma, then
        at a space, and only as a last resort in the middle of a word.
    """
    pieces = []
    while len(line) > limit:
        comma = line.rfind(", ", 0, limit)
        if comma > 0:
            cut = comma + 1
        else:
            space = line.rfind(" ", 0, limit)
            cut = space if space > 0 else limit
        pieces.append(line[:cut].rstrip())
        line = line[cut:].lstrip()
    pieces.append(line)
    return pieces


def split_message(text: str, limit: int = PART_LIMIT) -> list[str]:
    """Split a notification into parts that Telegram will accept.

    Whole lines are kept together whenever possible, so a report with one
    change per line is split between changes. A single line longer than the
    limit (for example a long list of new article numbers) is split after a
    comma.

    Args:
        text: The full notification text.
        limit: Maximum length of each part.

    Returns:
        A list with one or more non-empty parts, each at most ``limit``
        characters long. Text that already fits is returned unchanged.
    """
    if len(text) <= limit:
        return [text]

    parts = []
    current = ""
    for line in text.split("\n"):
        for piece in _split_long_line(line, limit):
            candidate = f"{current}\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                parts.append(current)
                current = piece
    if current:
        parts.append(current)
    return parts


def _telegram_description(response) -> str:
    """Return Telegram's own explanation of a rejected request, if any.

    Args:
        response: The HTTP response attached to a failed request, or None.

    Returns:
        The ``description`` field of the Bot API error, or an empty string.
    """
    try:
        return str(response.json().get("description") or "")
    except (AttributeError, ValueError):
        return ""


def _send_part(token: str, chat_id: str, text: str, timeout: float) -> None:
    """Send one already-sized message and raise a token-free error on failure.

    Args:
        token: Telegram bot token.
        chat_id: Destination chat identifier.
        text: Message text, at most ``TELEGRAM_MESSAGE_LIMIT`` characters.
        timeout: Maximum time to wait for the Telegram API, in seconds.

    Raises:
        TelegramDeliveryError: If the request fails or Telegram rejects it.
    """
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=timeout,
        )
        response.raise_for_status()
        accepted = bool(response.json().get("ok"))
    except (requests.RequestException, ValueError) as error:
        reason = sanitize_error(str(error)).replace(token, "<redacted>")
        description = _telegram_description(getattr(error, "response", None))
        if description:
            reason = f"{reason} ({description})"
        # "from None" drops the original exception, whose text holds the token.
        raise TelegramDeliveryError(f"Telegram request failed: {reason}") from None
    if not accepted:
        raise TelegramDeliveryError("Telegram rejected the notification")


def send_telegram_message(text: str, timeout: float = 15) -> None:
    """Send a message to the chat configured for the administrator.

    Text longer than Telegram's limit is sent as several consecutive messages
    labelled ``[1/3]``, ``[2/3]``, ... so a large report is delivered instead
    of being rejected.

    Args:
        text: Plain-text notification to send.
        timeout: Maximum time to wait for the Telegram API per message, in
            seconds.

    Raises:
        TelegramDeliveryError: If a request fails or Telegram rejects a message.
            The error text never contains the bot token. When a later part
            fails, the earlier parts have already been delivered.
        KeyError: If the bot token or chat ID is not configured.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    parts = split_message(text)
    for number, part in enumerate(parts, start=1):
        if len(parts) > 1:
            part = f"[{number}/{len(parts)}]\n{part}"
        _send_part(token, chat_id, part, timeout)
        if number < len(parts):
            time.sleep(PAUSE_BETWEEN_PARTS_SECONDS)

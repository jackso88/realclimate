"""Exceptions raised by the notification service."""


class TelegramDeliveryError(RuntimeError):
    """Raised when Telegram does not accept a notification.

    The message never contains the bot token: request errors from ``requests``
    embed the full API URL (``.../bot<TOKEN>/sendMessage``), so it is redacted
    before the exception is created.
    """

"""Tests for how notification envelopes are turned into Telegram text."""

import logging
from unittest.mock import Mock, patch

from app.messaging.models import Envelope
from app.messaging.topics import CORE_NOTIFICATIONS
from app.notifications import consumer
from app.notifications.consumer import handle_notification


@patch("app.notifications.consumer.send_telegram_message")
def test_failure_text_names_the_service_and_error_type(send):
    payload = {"service": "core", "error_type": "ValueError", "error": "bad input"}

    handle_notification(Envelope.create("failure", payload), None)

    send.assert_called_once_with("Ошибка сервиса core (ValueError): bad input")


@patch("app.notifications.consumer.send_telegram_message")
def test_failure_text_falls_back_to_defaults_for_missing_fields(send):
    handle_notification(Envelope.create("failure", {}), None)

    send.assert_called_once_with("Ошибка сервиса unknown (Error): ")


@patch("app.notifications.consumer.send_telegram_message")
def test_change_report_lists_one_change_per_line(send):
    changes = ["Артикул A, цена изменилась", "Артикул B, количество изменилось"]

    handle_notification(Envelope.create("detailed_changes", {"changes": changes}), None)

    send.assert_called_once_with(
        "Изменения каталога:\nАртикул A, цена изменилась\n"
        "Артикул B, количество изменилось"
    )


@patch("app.notifications.consumer.send_telegram_message")
def test_change_report_without_a_changes_key_is_ignored(send):
    handle_notification(Envelope.create("detailed_changes", {}), None)

    send.assert_not_called()


@patch("app.notifications.consumer.send_telegram_message")
def test_change_report_with_null_changes_is_ignored(send):
    handle_notification(Envelope.create("detailed_changes", {"changes": None}), None)

    send.assert_not_called()


@patch("app.notifications.consumer.send_telegram_message")
def test_unknown_commands_are_logged_and_not_sent(send, caplog):
    with caplog.at_level(logging.WARNING, logger="app.notifications.consumer"):
        handle_notification(Envelope.create("surprise", {}), None)

    send.assert_not_called()
    assert "Unknown notification command: surprise" in caplog.text


def test_main_runs_the_notification_worker(monkeypatch):
    run_consumer = Mock()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    consumer.main()

    run_consumer.assert_called_once_with(
        "localhost:9092",
        CORE_NOTIFICATIONS,
        "telegram-notifications",
        handle_notification,
        service_name="notifications",
    )

"""Tests for the email notification Kafka consumer."""

import logging
import runpy
import smtplib
import warnings
from unittest.mock import Mock

import pytest

from app.messaging.exceptions import RetryableMessageError
from app.messaging.topics import CORE_NOTIFICATIONS
from app.notifications.email import consumer
from app.notifications.email.consumer import handle_notification
from app.notifications.email.exceptions import EmailDeliveryError, EmailRejectedError
from app.notifications.email.sender import CORRELATION_HEADER


def test_detailed_changes_are_emailed_with_the_correlation_id(
    fake_smtp, detailed_changes_envelope, changes, email_settings
):
    handle_notification(detailed_changes_envelope, None, email_settings)

    message, _, to_addrs = fake_smtp.connection.sent[0]
    assert to_addrs == ["first@example.invalid", "second@example.invalid"]
    assert message[CORRELATION_HEADER] == "corr-123"
    body = message.get_content()
    assert "corr-123" not in body
    assert all(change in body for change in changes)


@pytest.mark.parametrize(
    ("command", "payload"),
    [
        ("failure", {"service": "core", "error": "boom"}),
        ("debug", {"message": "heartbeat"}),
        ("catalogue_processed", {"detailed_changes": ["x"]}),
        ("", {}),
    ],
)
def test_other_commands_are_ignored(
    fake_smtp, make_envelope, email_settings, caplog, command, payload
):
    with caplog.at_level(logging.DEBUG):
        handle_notification(
            make_envelope(command or "other", payload), None, email_settings
        )

    assert fake_smtp.connections == []
    assert "[correlation_id=corr-123]" in caplog.text


@pytest.mark.parametrize("payload", [{}, {"changes": []}, {"changes": None}])
def test_empty_reports_are_ignored(
    fake_smtp, make_envelope, email_settings, caplog, payload
):
    with caplog.at_level(logging.INFO):
        handle_notification(
            make_envelope("detailed_changes", payload), None, email_settings
        )

    assert fake_smtp.connections == []
    assert "empty detailed_changes report [correlation_id=corr-123]" in caplog.text


@pytest.mark.parametrize("payload", [{"changes": "text"}, {"changes": [1, 2]}])
def test_malformed_reports_are_ignored_and_logged(
    fake_smtp, make_envelope, email_settings, caplog, payload
):
    with caplog.at_level(logging.WARNING):
        handle_notification(
            make_envelope("detailed_changes", payload), None, email_settings
        )

    assert fake_smtp.connections == []
    assert "malformed detailed_changes payload [correlation_id=corr-123]" in caplog.text


def test_report_without_correlation_id_is_still_sent(
    fake_smtp, make_envelope, changes, email_settings
):
    message = make_envelope("detailed_changes", {"changes": changes}, None)

    handle_notification(message, None, email_settings)

    assert fake_smtp.connection.sent[0][0][CORRELATION_HEADER] is None


def test_temporary_failures_propagate_so_the_record_is_retried(
    fake_smtp, detailed_changes_envelope, email_settings
):
    fake_smtp.errors["connect"] = OSError("down")

    with pytest.raises(RetryableMessageError):
        handle_notification(detailed_changes_envelope, None, email_settings)


def test_permanent_failures_propagate_without_a_retry(
    fake_smtp, detailed_changes_envelope, email_settings
):
    fake_smtp.errors["send_message"] = smtplib.SMTPDataError(554, b"no")

    with pytest.raises(EmailRejectedError) as caught:
        handle_notification(detailed_changes_envelope, None, email_settings)

    assert not isinstance(caught.value, EmailDeliveryError)


def test_main_subscribes_to_the_notifications_topic(monkeypatch, set_email_env):
    run_consumer = Mock()
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)

    consumer.main()

    args = run_consumer.call_args
    assert args.args[:3] == ("kafka:9092", CORE_NOTIFICATIONS, "email-notifications")
    assert args.kwargs["service_name"] == "notifications_email"
    assert args.args[3].keywords["settings"].smtp_host == "smtp.example.invalid"


def test_module_runs_as_a_container_entrypoint(monkeypatch, set_email_env):
    run_consumer = Mock()
    monkeypatch.setattr(logging, "basicConfig", Mock())
    monkeypatch.setattr("app.messaging.kafka.run_consumer", run_consumer)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("app.notifications.email.consumer", run_name="__main__")

    run_consumer.assert_called_once()
    assert run_consumer.call_args.args[1] == CORE_NOTIFICATIONS

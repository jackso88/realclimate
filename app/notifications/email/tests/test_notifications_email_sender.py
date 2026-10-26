"""Tests for building and sending notification emails."""

import logging
import smtplib

import pytest

from app.messaging.exceptions import RetryableMessageError
from app.notifications.email.exceptions import (
    EmailDeliveryError,
    EmailError,
    EmailRejectedError,
)
from app.notifications.email.models import EmailNotification
from app.notifications.email.sender import (
    CORRELATION_HEADER,
    build_email_message,
    build_notification,
    send_email,
)


def test_notification_lists_every_change_without_the_correlation_id(changes):
    notification = build_notification(changes, "corr-123")

    assert notification.subject == "Catalogue changes detected: 2"
    assert notification.correlation_id == "corr-123"
    assert notification.body.splitlines() == [
        "Catalogue changes (2):",
        "",
        *changes,
    ]
    assert "corr-123" not in notification.body


def test_notification_without_correlation_id_has_the_same_body(changes):
    notification = build_notification(changes)

    assert notification.correlation_id is None
    assert notification.body == build_notification(changes, "corr-123").body


def test_message_is_addressed_to_both_recipients(notification, email_settings):
    message = build_email_message(notification, email_settings)

    assert message["From"] == "notifications@example.invalid"
    assert message["To"] == "first@example.invalid, second@example.invalid"
    assert message["Subject"] == notification.subject
    assert message["Message-ID"].endswith("@example.invalid>")
    assert message["Date"]
    assert message.get_content().strip() == notification.body


def test_message_carries_the_correlation_id_header(notification, email_settings):
    message = build_email_message(notification, email_settings)

    assert message[CORRELATION_HEADER] == "corr-123"


def test_correlation_header_is_flattened_to_one_line(email_settings):
    notification = EmailNotification(
        subject="s", body="b", correlation_id="abc\r\nBcc: attacker@evil.invalid"
    )

    message = build_email_message(notification, email_settings)

    assert message[CORRELATION_HEADER] == "abc Bcc: attacker@evil.invalid"
    assert message["Bcc"] is None


def test_message_without_correlation_id_has_no_header(email_settings):
    message = build_email_message(
        EmailNotification(subject="s", body="b"), email_settings
    )

    assert message[CORRELATION_HEADER] is None


def test_starttls_connection_logs_in_and_sends_once(
    fake_smtp, notification, email_settings
):
    send_email(notification, email_settings)

    connection = fake_smtp.connection
    assert connection.kind == "plain"
    assert (connection.host, connection.port) == ("smtp.example.invalid", 587)
    assert connection.timeout == 5
    assert connection.calls == [
        "starttls",
        ("login", "mailer", "s3cret-pass"),
        "send_message",
        "quit",
    ]
    message, from_addr, to_addrs = connection.sent[0]
    assert from_addr == "notifications@example.invalid"
    assert to_addrs == ["first@example.invalid", "second@example.invalid"]
    assert message[CORRELATION_HEADER] == "corr-123"


def test_ssl_connection_skips_starttls(fake_smtp, notification, make_email_settings):
    send_email(notification, make_email_settings(EMAIL_SMTP_SECURITY="ssl"))

    connection = fake_smtp.connection
    assert connection.kind == "ssl"
    assert connection.context is not None
    assert "starttls" not in connection.calls
    assert connection.sent


def test_unencrypted_connection_without_credentials_only_sends(
    fake_smtp, notification, make_email_settings
):
    settings = make_email_settings(
        EMAIL_SMTP_SECURITY="none", EMAIL_SMTP_USERNAME="", EMAIL_SMTP_PASSWORD=""
    )

    send_email(notification, settings)

    assert fake_smtp.connection.calls == ["send_message", "quit"]


def test_recipients_that_are_refused_are_logged_but_not_fatal(
    fake_smtp, notification, email_settings, caplog
):
    fake_smtp.refused = {"second@example.invalid": (550, b"no such user")}

    with caplog.at_level(logging.INFO):
        send_email(notification, email_settings)

    assert "refused some recipients [correlation_id=corr-123]" in caplog.text
    assert "second@example.invalid" in caplog.text
    assert "Sent email to 1 recipients [correlation_id=corr-123]" in caplog.text


def test_successful_delivery_is_logged_with_the_correlation_id(
    fake_smtp, notification, email_settings, caplog
):
    with caplog.at_level(logging.INFO):
        send_email(notification, email_settings)

    assert "Sent email to 2 recipients [correlation_id=corr-123]" in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        smtplib.SMTPRecipientsRefused({"a@x.invalid": (550, b"rejected")}),
        smtplib.SMTPSenderRefused(553, b"sender not allowed", "a@x.invalid"),
        smtplib.SMTPDataError(554, b"message rejected as spam"),
    ],
)
def test_permanent_refusals_are_not_retried(
    fake_smtp, notification, email_settings, error
):
    fake_smtp.errors["send_message"] = error

    with pytest.raises(EmailRejectedError, match="correlation_id=corr-123") as caught:
        send_email(notification, email_settings)

    assert not isinstance(caught.value, RetryableMessageError)
    assert isinstance(caught.value, EmailError)


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("connect", ConnectionRefusedError("connection refused")),
        ("connect", TimeoutError("timed out")),
        ("connect", smtplib.SMTPConnectError(421, b"service not available")),
        ("starttls", smtplib.SMTPNotSupportedError("STARTTLS not supported")),
        ("login", smtplib.SMTPAuthenticationError(535, b"bad credentials")),
        ("send_message", smtplib.SMTPServerDisconnected("connection lost")),
        ("send_message", smtplib.SMTPDataError(451, b"try again later")),
    ],
)
def test_temporary_failures_are_retryable(
    fake_smtp, notification, email_settings, step, error
):
    fake_smtp.errors[step] = error

    with pytest.raises(EmailDeliveryError, match="correlation_id=corr-123") as caught:
        send_email(notification, email_settings)

    assert isinstance(caught.value, RetryableMessageError)


def test_password_is_redacted_from_error_text(fake_smtp, notification, email_settings):
    fake_smtp.errors["login"] = smtplib.SMTPAuthenticationError(
        535, b"login failed for s3cret-pass"
    )

    with pytest.raises(EmailDeliveryError) as caught:
        send_email(notification, email_settings)

    assert "s3cret-pass" not in str(caught.value)
    assert "<redacted>" in str(caught.value)
    assert caught.value.__cause__ is None


def test_errors_without_a_password_keep_their_text(
    fake_smtp, notification, make_email_settings
):
    fake_smtp.errors["connect"] = OSError("network unreachable")
    settings = make_email_settings(EMAIL_SMTP_USERNAME="", EMAIL_SMTP_PASSWORD="")

    with pytest.raises(EmailDeliveryError, match="network unreachable"):
        send_email(notification, settings)


def test_notification_without_correlation_id_still_reports_errors(
    fake_smtp, email_settings
):
    fake_smtp.errors["connect"] = OSError("down")

    with pytest.raises(EmailDeliveryError, match="correlation_id=None"):
        send_email(EmailNotification(subject="s", body="b"), email_settings)

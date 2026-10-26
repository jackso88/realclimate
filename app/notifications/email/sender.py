"""SMTP client that builds and delivers change-report emails."""

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from app.messaging.kafka import sanitize_error
from app.notifications.email.exceptions import EmailDeliveryError, EmailRejectedError
from app.notifications.email.models import EmailNotification, EmailSettings

logger = logging.getLogger(__name__)

SUBJECT_TEMPLATE = "Catalogue changes detected: {count}"
CORRELATION_HEADER = "X-Correlation-ID"
PERMANENT_SMTP_CODE_FLOOR = 500


def build_notification(
    changes: list[str], correlation_id: str | None = None
) -> EmailNotification:
    """Turn a change report into an email subject and plain-text body.

    Args:
        changes: Non-empty list of human-readable change descriptions; each
            entry is written on its own line, unchanged.
        correlation_id: Optional pipeline ID. It is not written into the body;
            it travels in the ``X-Correlation-ID`` header and in log lines.

    Returns:
        The notification ready to be sent.
    """
    lines = [f"Catalogue changes ({len(changes)}):", "", *changes]
    return EmailNotification(
        subject=SUBJECT_TEMPLATE.format(count=len(changes)),
        body="\n".join(lines),
        correlation_id=correlation_id,
    )


def build_email_message(
    notification: EmailNotification, settings: EmailSettings
) -> EmailMessage:
    """Create the MIME message for a notification.

    Args:
        notification: Subject, body, and correlation ID to send.
        settings: Service settings that provide the sender and recipients.

    Returns:
        A plain-text message addressed to every configured recipient. When the
        notification has a correlation ID it is also set in the
        ``X-Correlation-ID`` header, flattened to one line so it cannot inject
        extra headers.
    """
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    message["Subject"] = notification.subject
    message["Date"] = format_datetime(datetime.now(timezone.utc))
    message["Message-ID"] = make_msgid(domain=settings.sender.rpartition("@")[2])
    if notification.correlation_id:
        message[CORRELATION_HEADER] = " ".join(notification.correlation_id.split())
    message.set_content(notification.body)
    return message


def _open_connection(settings: EmailSettings) -> smtplib.SMTP:
    """Open an SMTP connection using the configured host, port, and security.

    Args:
        settings: Service settings with the SMTP endpoint and timeout.

    Returns:
        A connected client; ``smtplib.SMTP_SSL`` when ``smtp_security`` is
        ``ssl`` and a plain ``smtplib.SMTP`` otherwise.
    """
    if settings.smtp_security == "ssl":
        return smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
            context=ssl.create_default_context(),
        )
    return smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    )


def _reason(error: Exception, settings: EmailSettings) -> str:
    """Describe an SMTP failure without leaking credentials.

    Args:
        error: Exception raised by ``smtplib`` or the network stack.
        settings: Service settings whose password must not appear in the text.

    Returns:
        The exception class and sanitized message.
    """
    text = sanitize_error(str(error))
    if settings.smtp_password is not None:
        text = text.replace(settings.smtp_password.get_secret_value(), "<redacted>")
    return f"{type(error).__name__}: {text}"


def send_email(notification: EmailNotification, settings: EmailSettings) -> None:
    """Deliver one notification to all configured recipients in a single message.

    All recipients share one SMTP transaction, so a retry after a failure never
    sends a second copy to a recipient who already received the first.

    Args:
        notification: Subject, body, and correlation ID to send.
        settings: SMTP endpoint, credentials, sender, and recipients.

    Raises:
        EmailRejectedError: If the server permanently refuses the message
            (all recipients, the sender, or a 5xx answer to the message data).
        EmailDeliveryError: If delivery failed for a possibly temporary reason
            such as a network error, timeout, 4xx answer, or bad credentials.
    """
    message = build_email_message(notification, settings)
    trace = f" [correlation_id={notification.correlation_id}]"
    try:
        with _open_connection(settings) as smtp:
            if settings.smtp_security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username and settings.smtp_password:
                smtp.login(
                    settings.smtp_username, settings.smtp_password.get_secret_value()
                )
            refused = smtp.send_message(
                message, from_addr=settings.sender, to_addrs=settings.recipients
            )
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as error:
        raise EmailRejectedError(
            f"SMTP server refused the email{trace}: {_reason(error, settings)}"
        ) from None
    except smtplib.SMTPDataError as error:
        failure = (
            EmailRejectedError
            if error.smtp_code >= PERMANENT_SMTP_CODE_FLOOR
            else EmailDeliveryError
        )
        raise failure(
            f"SMTP server rejected the message data{trace}: "
            f"{_reason(error, settings)}"
        ) from None
    except (smtplib.SMTPException, OSError) as error:
        raise EmailDeliveryError(
            f"Email delivery failed{trace}: {_reason(error, settings)}"
        ) from None
    if refused:
        logger.warning(
            "SMTP server refused some recipients%s: %s",
            trace,
            ", ".join(sorted(refused)),
        )
    logger.info(
        "Sent email to %d recipients%s", len(settings.recipients) - len(refused), trace
    )

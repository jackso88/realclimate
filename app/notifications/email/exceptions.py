"""Exceptions raised by the email notification service."""

from app.messaging.exceptions import RetryableMessageError


class EmailError(RuntimeError):
    """Base class for failures raised while delivering an email notification.

    Messages never contain the SMTP password: error text received from the
    mail server or the network stack is sanitized before it is stored here.
    """


class EmailDeliveryError(EmailError, RetryableMessageError):
    """Raised when delivery failed for a reason that may go away on its own.

    Examples are an unreachable SMTP server, a dropped connection, a temporary
    (4xx) rejection, or rejected credentials that an operator can still fix.
    The Kafka consumer keeps the record uncommitted and retries it later, so
    the notification is not lost.
    """


class EmailRejectedError(EmailError):
    """Raised when the SMTP server permanently refuses this notification.

    Retrying cannot help (for example, every recipient or the sender address
    was refused, or the server answered with a 5xx data error), so the consumer
    logs the failure and moves on instead of blocking the topic.
    """

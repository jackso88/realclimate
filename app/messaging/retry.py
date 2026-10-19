"""Classification helpers for transient failures in message handlers."""

import requests

from app.messaging.exceptions import RequestTimeoutError, RetryableMessageError


def is_retryable_transport_error(error: Exception) -> bool:
    """Return whether a failure is likely to clear without changing input.

    Network interruptions and selected HTTP/API status codes are retried by
    leaving the Kafka record uncommitted. Authentication, validation, and
    other client errors remain non-retryable so they do not block a partition.

    Args:
        error: Exception raised while calling an external HTTP or Google API.

    Returns:
        ``True`` for connection/time-out errors and transient server responses.
    """
    if isinstance(
        error,
        (
            RetryableMessageError,
            RequestTimeoutError,
            requests.Timeout,
            requests.ConnectionError,
        ),
    ):
        return True

    if isinstance(error, requests.HTTPError):
        status_code = error.response.status_code if error.response else None
        return status_code in {408, 425, 429} or (
            status_code is not None and status_code >= 500
        )

    if isinstance(error, requests.RequestException):
        return True

    # gspread wraps Google API responses in APIError rather than requests' HTTPError.
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if error.__class__.__name__ == "APIError" and status_code is not None:
        return status_code in {408, 425, 429} or status_code >= 500

    return False

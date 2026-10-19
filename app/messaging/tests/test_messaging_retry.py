"""Tests for classifying retryable external-service failures."""

from types import SimpleNamespace

import pytest
import requests

from app.messaging.exceptions import RequestTimeoutError, RetryableMessageError
from app.messaging.retry import is_retryable_transport_error


@pytest.mark.parametrize(
    "error",
    [
        RetryableMessageError("retry"),
        RequestTimeoutError("timeout"),
        requests.Timeout("timeout"),
        requests.ConnectionError("offline"),
        requests.RequestException("other transport failure"),
    ],
)
def test_transport_errors_are_retryable(error):
    assert is_retryable_transport_error(error) is True


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
def test_retryable_http_statuses(status):
    error = requests.HTTPError(response=SimpleNamespace(status_code=status))

    assert is_retryable_transport_error(error) is True


@pytest.mark.parametrize("status", [400, 401, 404])
def test_non_retryable_http_statuses(status):
    error = requests.HTTPError(response=SimpleNamespace(status_code=status))

    assert is_retryable_transport_error(error) is False


def test_http_error_without_response_is_not_retryable():
    assert is_retryable_transport_error(requests.HTTPError("bad request")) is False


@pytest.mark.parametrize("status", [408, 425, 429, 500, 503])
def test_google_api_transient_statuses_are_retryable(status):
    error = type("APIError", (Exception,), {})()
    error.response = SimpleNamespace(status_code=status)

    assert is_retryable_transport_error(error) is True


@pytest.mark.parametrize("status", [400, 403, 404])
def test_google_api_client_errors_are_not_retryable(status):
    error = type("APIError", (Exception,), {})()
    error.response = SimpleNamespace(status_code=status)

    assert is_retryable_transport_error(error) is False


def test_unknown_error_is_not_retryable():
    assert is_retryable_transport_error(ValueError("invalid input")) is False

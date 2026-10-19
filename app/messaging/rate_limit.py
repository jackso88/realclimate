"""Helpers for applying central Kafka permits to existing HTTP sessions."""

from threading import Lock

import requests

from app.messaging.rate_limit_client import RateLimitClient

_CLIENTS: dict[tuple[str, str], RateLimitClient] = {}
_CLIENTS_LOCK = Lock()


def get_rate_limit_client(bootstrap_servers: str, service_name: str) -> RateLimitClient:
    """Return one long-lived rate-limit client for this service process.

    Args:
        bootstrap_servers: Kafka brokers configured for the calling service.
        service_name: Stable name used to distinguish its reply consumer group.

    Returns:
        A shared client with a persistent background response consumer.
    """
    key = (bootstrap_servers, service_name)
    with _CLIENTS_LOCK:
        if key not in _CLIENTS:
            _CLIENTS[key] = RateLimitClient(bootstrap_servers, service_name)
        return _CLIENTS[key]


def rate_limit_session(
    session,
    bootstrap_servers: str,
    service_name: str,
    bucket: str,
):
    """Add a permit check before every request made through a requests session.

    Args:
        session: Existing ``requests.Session`` or compatible authorized session.
        bootstrap_servers: Kafka brokers used to contact the limiter.
        service_name: Stable calling service name.
        bucket: Shared quota name for the external account or API.

    Returns:
        The same session with its request method guarded by the rate limiter.
    """
    if not callable(getattr(session, "request", None)):
        raise TypeError(
            "Rate-limited HTTP session must provide a callable request method"
        )
    original_request = session.request

    def request_with_permit(method, url, *args, **kwargs):
        get_rate_limit_client(bootstrap_servers, service_name).acquire(bucket)
        return original_request(method, url, *args, **kwargs)

    session.request = request_with_permit
    return session


def acquire_rate_limit(
    bootstrap_servers: str,
    service_name: str,
    bucket: str,
) -> None:
    """Acquire one permit for a direct HTTP call that does not use a session."""
    get_rate_limit_client(bootstrap_servers, service_name).acquire(bucket)


def rate_limit_google_client(client, bootstrap_servers: str) -> None:
    """Guard Google API and OAuth refresh HTTP sessions with one quota bucket.

    ``google-auth`` uses a separate private requests session to refresh access
    tokens. Guarding only gspread's main authorized session would leave that
    outbound request outside the shared quota, so both sessions are wrapped.

    Args:
        client: Authorized gspread client.
        bootstrap_servers: Kafka brokers used to contact the limiter.
    """
    authorized_session = client.http_client.session
    rate_limit_session(
        authorized_session,
        bootstrap_servers,
        "downloader_reference",
        "google:sheets",
    )
    refresh_session = getattr(authorized_session, "_auth_request_session", None)
    if isinstance(refresh_session, requests.Session):
        rate_limit_session(
            refresh_session,
            bootstrap_servers,
            "downloader_reference",
            "google:sheets",
        )
        # Retries performed inside HTTPAdapter bypass the session.request wrapper.
        for adapter in refresh_session.adapters.values():
            adapter.max_retries = 0

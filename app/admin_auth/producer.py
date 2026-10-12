"""Kafka client helper for requesting CMS sessions from admin_auth."""

from app.admin_auth.models import SessionSnapshot
from app.messaging.kafka import KafkaBus
from app.messaging.topics import ADMIN_AUTH_REQUESTS


def request_session(
    bus: KafkaBus,
    response_topic: str,
    response_group: str,
    timeout: float = 60,
):
    """Request an authenticated session snapshot over Kafka.

    Args:
        bus: Kafka bus used to send the request and receive its response.
        response_topic: Topic subscribed to for this request's reply.
        response_group: Consumer group used to receive the reply.
        timeout: Maximum number of seconds to wait for the auth service.

    Returns:
        A local ``requests.Session`` restored from the returned cookies and
        headers.

    Raises:
        RemoteServiceError: If the auth service reports a failure.
        RequestTimeoutError: If no matching response arrives in time.
    """
    response = bus.request(
        ADMIN_AUTH_REQUESTS,
        response_topic,
        "create_session",
        {},
        timeout=timeout,
        response_group=response_group,
    )
    return SessionSnapshot.from_payload(response.payload).create_session()

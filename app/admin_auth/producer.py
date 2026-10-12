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
    """Request a session snapshot and rebuild a local requests.Session."""
    response = bus.request(
        ADMIN_AUTH_REQUESTS,
        response_topic,
        "create_session",
        {},
        timeout=timeout,
        response_group=response_group,
    )
    return SessionSnapshot.from_payload(response.payload).create_session()

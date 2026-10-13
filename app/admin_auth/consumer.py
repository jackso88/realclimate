"""Kafka consumer for admin session creation requests."""

import logging
import os

from app.admin_auth.auth import create_session_snapshot
from app.admin_auth.config import load_settings
from app.admin_auth.session_cache import SessionSnapshotCache
from app.logging_config import configure_logging
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.topics import ADMIN_AUTH_REQUESTS

logger = logging.getLogger(__name__)
session_cache = SessionSnapshotCache()


def handle_request(message, bus) -> None:
    """Authenticate and publish a session snapshot or request error.

    Args:
        message: Kafka request envelope, including its reply topic and ID.
        bus: Shared Kafka bus used to publish the correlated reply.
    """
    try:
        settings = load_settings()
        snapshot = session_cache.get(settings, create_session_snapshot)
        publish_reply(bus, message, snapshot.to_payload())
    except Exception as error:
        logger.exception("Admin authentication request failed")
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the admin authentication Kafka worker."""
    configure_logging()
    run_consumer(
        os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        ADMIN_AUTH_REQUESTS,
        "admin-auth-service",
        handle_request,
        service_name="admin_auth",
    )


if __name__ == "__main__":
    main()

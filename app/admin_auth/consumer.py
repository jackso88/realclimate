"""Kafka consumer for admin session creation requests."""

import logging
import os

from app.admin_auth.auth import create_session_snapshot
from app.admin_auth.config import load_settings
from app.logging_config import configure_logging
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.topics import ADMIN_AUTH_REQUESTS

logger = logging.getLogger(__name__)


def handle_request(message, bus) -> None:
    """Authenticate and answer a session creation request."""
    try:
        snapshot = create_session_snapshot(load_settings())
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
    )


if __name__ == "__main__":
    main()

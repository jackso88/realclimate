"""Kafka consumer for admin session creation requests."""

import logging
from functools import partial

from app.admin_auth.auth import create_session_snapshot
from app.admin_auth.config import configure_logging, load_settings
from app.admin_auth.models import AdminSettings
from app.admin_auth.session_cache import SessionSnapshotCache
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.exceptions import RetryableMessageError
from app.messaging.topics import ADMIN_AUTH_REQUESTS

logger = logging.getLogger(__name__)
session_cache = SessionSnapshotCache()


def handle_request(message, bus, settings: AdminSettings | None = None) -> None:
    """Authenticate and publish a session snapshot or request error.

    Args:
        message: Kafka request envelope, including its reply topic and ID.
        bus: Shared Kafka bus used to publish the correlated reply.
        settings: Optional process settings injected by ``main``. Direct calls
            load settings on demand, while the worker reuses one instance.
    """
    try:
        if settings is None:
            settings = load_settings()
        snapshot = session_cache.get(settings, create_session_snapshot)
        publish_reply(bus, message, snapshot.to_payload())
    except Exception as error:
        logger.exception("Admin authentication request failed")
        if isinstance(error, RetryableMessageError):
            raise
        publish_reply(bus, message, error=str(error))


def main() -> None:
    """Run the admin authentication Kafka worker."""
    configure_logging()
    settings = load_settings()
    run_consumer(
        settings.bootstrap_servers,
        ADMIN_AUTH_REQUESTS,
        "admin-auth-service",
        partial(handle_request, settings=settings),
        service_name="admin_auth",
    )


if __name__ == "__main__":
    main()

"""Kafka worker that grants outbound HTTP permits using Redis state."""

import logging
from functools import partial

from app.contracts.models import Envelope
from app.messaging.kafka import publish_reply, run_consumer
from app.messaging.topics import RATE_LIMIT_REQUESTS
from app.rate_limiter.config import configure_logging, load_settings
from app.rate_limiter.models import RateLimiterSettings
from app.rate_limiter.redis_client import RedisClient, RedisCommandError
from app.rate_limiter.redis_store import RedisPermitStore

logger = logging.getLogger(__name__)


def handle_request(
    message: Envelope,
    bus,
    settings: RateLimiterSettings,
    store: RedisPermitStore,
) -> None:
    """Decide whether a caller may issue its next external HTTP request.

    Args:
        message: Permit request with a configured bucket and reply topic.
        bus: Kafka producer used to send the correlated decision.
        settings: Central quota settings loaded once at worker startup.
        store: Redis-backed atomic permit reservation store.

    Raises:
        RetryableMessageError: If Redis is unavailable, after returning a
            retryable error to the caller.
    """
    if message.command != "acquire_permit":
        publish_reply(
            bus, message, error=f"Unsupported rate-limit command: {message.command}"
        )
        return
    bucket = message.payload.get("bucket")
    if not isinstance(bucket, str) or not bucket:
        publish_reply(bus, message, error="Rate-limit request is missing a bucket")
        return
    try:
        interval_ms = settings.interval_for(bucket)
    except KeyError as error:
        publish_reply(bus, message, error=str(error))
        return

    try:
        granted, retry_after_ms = store.acquire(bucket, interval_ms)
    except (OSError, RedisCommandError):
        logger.exception("Redis unavailable while reserving rate-limit permit")
        publish_reply(
            bus,
            message,
            error="RATE_LIMIT_BACKEND_UNAVAILABLE: Redis permit store failed",
        )
        return

    publish_reply(
        bus,
        message,
        {"granted": granted, "retry_after_ms": retry_after_ms},
    )


def main() -> None:
    """Run the rate-limiter consumer with a Redis-backed permit store."""
    configure_logging()
    settings = load_settings()
    store = RedisPermitStore(RedisClient.from_url(settings.redis_url))
    run_consumer(
        settings.bootstrap_servers,
        RATE_LIMIT_REQUESTS,
        "rate-limiter-service",
        partial(handle_request, settings=settings, store=store),
        service_name="rate_limiter",
    )


if __name__ == "__main__":
    main()

"""Kafka worker that executes database tasks on behalf of the other services."""

import logging
from collections.abc import Callable
from functools import partial
from typing import Any

from pydantic import ValidationError
from realclimate_contracts import Envelope
from realclimate_contracts.db import (
    ABSENT_ARTICLES_GET,
    ABSENT_ARTICLES_IMPORT_LEGACY,
    ABSENT_ARTICLES_REPLACE,
    AbsentArticlesImportLegacy,
    AbsentArticlesReplace,
    AbsentArticlesState,
)
from realclimate_contracts.topics import DB_REQUESTS
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.db_service.config import configure_logging, load_settings
from app.db_service.database import create_session_factory
from app.db_service.repository import (
    get_absent_articles,
    import_legacy_absent_articles,
    is_legacy_import_done,
    replace_absent_articles,
)
from app.messaging.kafka import publish_reply, run_consumer

logger = logging.getLogger(__name__)

DATABASE_UNAVAILABLE = "DB_BACKEND_UNAVAILABLE"


def _get_absent_articles(session: Session, _payload: dict[str, Any]) -> dict:
    state = AbsentArticlesState(
        articles=get_absent_articles(session),
        legacy_import_done=is_legacy_import_done(session),
    )
    return state.model_dump(mode="json")


def _replace_absent_articles(session: Session, payload: dict[str, Any]) -> dict:
    request = AbsentArticlesReplace.model_validate(payload)
    replace_absent_articles(session, request.articles)
    return {}


def _import_legacy_absent_articles(session: Session, payload: dict[str, Any]) -> dict:
    request = AbsentArticlesImportLegacy.model_validate(payload)
    import_legacy_absent_articles(session, request.articles)
    return {}


COMMAND_HANDLERS: dict[str, Callable[[Session, dict[str, Any]], dict]] = {
    ABSENT_ARTICLES_GET: _get_absent_articles,
    ABSENT_ARTICLES_REPLACE: _replace_absent_articles,
    ABSENT_ARTICLES_IMPORT_LEGACY: _import_legacy_absent_articles,
}


def handle_request(
    message: Envelope,
    bus,
    session_factory: sessionmaker[Session],
) -> None:
    """Execute one database command and publish its correlated reply.

    Every command runs in a single transaction that commits on success and
    rolls back on any failure. Failures are reported to the caller in the reply
    ``error`` field rather than raised, so the requester decides whether to
    retry; the request is then committed like any other handled message.

    Args:
        message: Command envelope from the ``db.requests`` topic.
        bus: Kafka bus used to publish the reply.
        session_factory: Factory that opens database sessions.
    """
    handler = COMMAND_HANDLERS.get(message.command)
    if handler is None:
        publish_reply(
            bus, message, error=f"Unsupported database command: {message.command}"
        )
        return
    try:
        with session_factory.begin() as session:
            result = handler(session, message.payload)
    except ValidationError as error:
        problem = error.errors(include_input=False, include_url=False)[0]
        location = ".".join(str(part) for part in problem["loc"])
        publish_reply(
            bus,
            message,
            error=f"Invalid {message.command} payload: {location}: {problem['msg']}",
        )
        return
    except SQLAlchemyError:
        logger.exception("Database command failed command=%s", message.command)
        publish_reply(
            bus,
            message,
            error=f"{DATABASE_UNAVAILABLE}: database command failed",
        )
        return
    publish_reply(bus, message, result)
    logger.info("Database command completed command=%s", message.command)


def main() -> None:
    """Run the database worker as a Kafka request/reply consumer."""
    configure_logging()
    settings = load_settings()
    session_factory = create_session_factory(settings.database_url)
    run_consumer(
        settings.bootstrap_servers,
        DB_REQUESTS,
        "db-service",
        partial(handle_request, session_factory=session_factory),
        service_name="db_service",
    )


if __name__ == "__main__":
    main()

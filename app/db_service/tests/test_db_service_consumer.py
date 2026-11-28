"""Tests for the database worker's Kafka command handling."""

from types import SimpleNamespace
from unittest.mock import Mock

from realclimate_contracts import Envelope
from realclimate_contracts.db import (
    ABSENT_ARTICLES_GET,
    ABSENT_ARTICLES_IMPORT_LEGACY,
    ABSENT_ARTICLES_REPLACE,
    AbsentArticlesState,
)
from realclimate_contracts.topics import DB_REQUESTS, DB_RESPONSES
from sqlalchemy.exc import OperationalError

from app.db_service import consumer
from app.db_service.models import DbServiceSettings


class FakeBus:
    def __init__(self):
        self.published = []

    def publish(self, topic, message, key=None):
        self.published.append((topic, message, key))


def request(command, payload=None, correlation_id="corr-1"):
    return Envelope.create(
        command, payload, correlation_id=correlation_id, reply_to=DB_RESPONSES
    )


def run(session_factory, command, payload=None):
    bus = FakeBus()
    consumer.handle_request(request(command, payload), bus, session_factory)
    assert len(bus.published) == 1
    topic, reply, key = bus.published[0]
    assert topic == DB_RESPONSES
    assert key == "corr-1"
    assert reply.correlation_id == "corr-1"
    return reply


def test_get_returns_the_state_of_an_empty_database(session_factory):
    reply = run(session_factory, ABSENT_ARTICLES_GET)

    assert reply.error is None
    state = AbsentArticlesState.model_validate(reply.payload)
    assert state.articles == []
    assert state.legacy_import_done is False


def test_replace_then_get_round_trips_the_articles(session_factory):
    replaced = run(session_factory, ABSENT_ARTICLES_REPLACE, {"articles": ["B", "A"]})
    state = AbsentArticlesState.model_validate(
        run(session_factory, ABSENT_ARTICLES_GET).payload
    )

    assert replaced.error is None
    assert state.articles == ["A", "B"]


def test_import_legacy_marks_the_import_done(session_factory):
    run(session_factory, ABSENT_ARTICLES_IMPORT_LEGACY, {"articles": ["A"]})
    state = AbsentArticlesState.model_validate(
        run(session_factory, ABSENT_ARTICLES_GET).payload
    )

    assert state.articles == ["A"]
    assert state.legacy_import_done is True


def test_an_unknown_command_is_answered_with_an_error(session_factory):
    reply = run(session_factory, "absent_articles.explode")

    assert "Unsupported database command" in reply.error


def test_an_invalid_payload_is_rejected_without_changing_the_database(
    session_factory,
):
    run(session_factory, ABSENT_ARTICLES_REPLACE, {"articles": ["KEEP"]})
    reply = run(session_factory, ABSENT_ARTICLES_REPLACE, {"articles": ["  "]})
    state = AbsentArticlesState.model_validate(
        run(session_factory, ABSENT_ARTICLES_GET).payload
    )

    assert "Invalid absent_articles.replace payload" in reply.error
    assert state.articles == ["KEEP"]


def test_a_database_failure_is_reported_to_the_requester(session_factory):
    class BrokenFactory:
        def begin(self):
            raise OperationalError("statement", {}, Exception("connection refused"))

    reply = run(BrokenFactory(), ABSENT_ARTICLES_GET)

    assert reply.error.startswith(consumer.DATABASE_UNAVAILABLE)
    assert "connection refused" not in reply.error


def test_a_request_without_a_reply_topic_is_executed_silently(session_factory):
    bus = FakeBus()
    message = Envelope.create(ABSENT_ARTICLES_REPLACE, {"articles": ["A"]})

    consumer.handle_request(message, bus, session_factory)

    assert bus.published == []
    state = AbsentArticlesState.model_validate(
        run(session_factory, ABSENT_ARTICLES_GET).payload
    )
    assert state.articles == ["A"]


def test_main_runs_a_heartbeating_consumer_on_the_request_topic(monkeypatch):
    run_consumer = Mock()
    factory = object()
    settings = DbServiceSettings.model_validate(
        {"DATABASE_URL": "postgresql://u:p@db/x"}
    )
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(consumer, "create_session_factory", lambda url: factory)
    monkeypatch.setattr(consumer, "run_consumer", run_consumer)

    consumer.main()

    args, kwargs = run_consumer.call_args
    assert args[:3] == (settings.bootstrap_servers, DB_REQUESTS, "db-service")
    assert args[3].func is consumer.handle_request
    assert args[3].keywords == {"session_factory": factory}
    assert kwargs == {"service_name": "db_service"}


def test_main_wiring_uses_the_configured_database_url(monkeypatch):
    created = []
    settings = SimpleNamespace(bootstrap_servers="kafka:9092", database_url="url")
    monkeypatch.setattr(consumer, "configure_logging", Mock())
    monkeypatch.setattr(consumer, "load_settings", lambda: settings)
    monkeypatch.setattr(
        consumer, "create_session_factory", lambda url: created.append(url)
    )
    monkeypatch.setattr(consumer, "run_consumer", Mock())

    consumer.main()

    assert created == ["url"]

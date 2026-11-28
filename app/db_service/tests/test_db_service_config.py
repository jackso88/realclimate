"""Tests for the database worker's configuration and engine helpers."""

import logging
from unittest.mock import Mock

import pytest

from app.db_service import config
from app.db_service.database import create_session_factory, normalize_database_url


def test_settings_require_the_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        config.load_settings()


def test_settings_error_does_not_echo_environment_secrets(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "super-secret-value")

    with pytest.raises(ValueError) as error:
        config.load_settings()

    assert "super-secret-value" not in str(error.value)


def test_settings_read_kafka_and_database_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/x")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")

    settings = config.load_settings()

    assert settings.database_url == "postgresql://u:p@db/x"
    assert settings.bootstrap_servers == "kafka:9092"


def test_configure_logging_sets_the_requested_level(monkeypatch):
    basic_config = Mock()
    monkeypatch.setattr(logging, "basicConfig", basic_config)

    config.configure_logging(logging.DEBUG)

    assert basic_config.call_args.kwargs["level"] == logging.DEBUG


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql://u:p@db/x", "postgresql+psycopg://u:p@db/x"),
        ("postgres://u:p@db/x", "postgresql+psycopg://u:p@db/x"),
        ("postgresql+psycopg://u:p@db/x", "postgresql+psycopg://u:p@db/x"),
        ("sqlite://", "sqlite://"),
    ],
)
def test_database_urls_select_the_psycopg_driver(url, expected):
    assert normalize_database_url(url) == expected


def test_session_factory_opens_working_sessions():
    factory = create_session_factory("sqlite://")

    with factory.begin() as session:
        assert session.connection() is not None

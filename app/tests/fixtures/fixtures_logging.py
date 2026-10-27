"""Fixtures that keep tests from reconfiguring real logging."""

import logging
from unittest.mock import Mock

import pytest


@pytest.fixture
def quiet_logging(monkeypatch):
    monkeypatch.setattr(logging, "basicConfig", Mock())
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


@pytest.fixture
def basic_config(monkeypatch):
    """Intercept logging.basicConfig so tests never reconfigure real logging."""
    mock = Mock()
    monkeypatch.setattr(logging, "basicConfig", mock)
    return mock

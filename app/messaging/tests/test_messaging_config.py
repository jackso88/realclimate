"""Tests for Kafka client configuration loading."""

import pytest

from app.messaging.config import load_client_settings
from app.messaging.models import KafkaClientSettings


def test_load_client_settings_reads_required_environment(monkeypatch):
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "test-user")
    monkeypatch.setenv("KAFKA_SASL_PASSWORD", "test-password")
    monkeypatch.setenv("KAFKA_SSL_CA_LOCATION", "/tmp/ca.pem")

    settings = load_client_settings("broker:9093")

    assert settings == KafkaClientSettings(
        bootstrap_servers="broker:9093",
        username="test-user",
        password="test-password",
        ca_location="/tmp/ca.pem",
    )
    assert settings.to_dict()["security.protocol"] == "SASL_SSL"
    assert settings.to_dict()["sasl.mechanism"] == "SCRAM-SHA-512"


@pytest.mark.parametrize(
    "missing_variable",
    ["KAFKA_SASL_USERNAME", "KAFKA_SASL_PASSWORD", "KAFKA_SSL_CA_LOCATION"],
)
def test_load_client_settings_rejects_missing_values(monkeypatch, missing_variable):
    values = {
        "KAFKA_SASL_USERNAME": "test-user",
        "KAFKA_SASL_PASSWORD": "test-password",
        "KAFKA_SSL_CA_LOCATION": "/tmp/ca.pem",
    }
    for name, value in values.items():
        if name == missing_variable:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match="must be configured"):
        load_client_settings("broker:9093")


def test_kafka_settings_round_trip():
    original = KafkaClientSettings(
        bootstrap_servers="broker:9093",
        username="user",
        password="password",
        ca_location="/tmp/ca.pem",
    )

    restored = KafkaClientSettings.from_dict(original.to_dict())

    assert restored == original


@pytest.mark.parametrize("value", [None, "", 42])
def test_kafka_settings_reject_invalid_required_property(value):
    settings = {
        "bootstrap.servers": "broker:9093",
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "SCRAM-SHA-512",
        "sasl.username": "user",
        "sasl.password": "password",
        "ssl.ca.location": "/tmp/ca.pem",
    }
    settings["sasl.username"] = value

    with pytest.raises(ValueError, match="sasl.username"):
        KafkaClientSettings.from_dict(settings)

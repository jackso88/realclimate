"""Tests for health monitor environment configuration."""

import pytest

from app.health_monitor.config import DEFAULT_MONITORED_SERVICES, load_settings


def test_load_settings_uses_defaults(monkeypatch):
    monkeypatch.delenv("HEALTH_MONITORED_SERVICES", raising=False)
    monkeypatch.delenv("HEALTH_HEARTBEAT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_STARTUP_GRACE_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_CHECK_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    settings = load_settings()

    assert settings.bootstrap_servers == "localhost:9092"
    assert settings.monitored_services == DEFAULT_MONITORED_SERVICES
    assert settings.heartbeat_timeout_seconds == 120
    assert settings.startup_grace_seconds == 180
    assert settings.check_interval_seconds == 10


def test_load_settings_reads_services_and_timing(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:9093")
    monkeypatch.setenv("HEALTH_MONITORED_SERVICES", "core, uploader,core")
    monkeypatch.setenv("HEALTH_HEARTBEAT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("HEALTH_STARTUP_GRACE_SECONDS", "90")
    monkeypatch.setenv("HEALTH_CHECK_INTERVAL_SECONDS", "5")

    settings = load_settings()

    assert settings.bootstrap_servers == "broker:9093"
    assert settings.monitored_services == ("core", "uploader")
    assert settings.heartbeat_timeout_seconds == 45
    assert settings.startup_grace_seconds == 90
    assert settings.check_interval_seconds == 5


@pytest.mark.parametrize("value", ["0", "-3", "invalid"])
def test_load_settings_rejects_invalid_intervals(monkeypatch, value):
    monkeypatch.setenv("HEALTH_CHECK_INTERVAL_SECONDS", value)

    with pytest.raises(ValueError, match="HEALTH_CHECK_INTERVAL_SECONDS"):
        load_settings()


def test_load_settings_rejects_empty_service_list(monkeypatch):
    monkeypatch.setenv("HEALTH_MONITORED_SERVICES", " , , ")

    with pytest.raises(ValueError, match="at least one service"):
        load_settings()

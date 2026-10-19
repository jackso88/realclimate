"""Tests for health monitor environment configuration."""

import pytest

from app.health_monitor.config import load_settings
from app.health_monitor.models import HealthMonitorEnvironment


def test_load_settings_uses_defaults(monkeypatch):
    monkeypatch.delenv("HEALTH_MONITORED_SERVICES", raising=False)
    monkeypatch.delenv("HEALTH_HEARTBEAT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_STARTUP_GRACE_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_CHECK_INTERVAL_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_MAX_BUSY_SECONDS", raising=False)
    monkeypatch.delenv("HEALTH_MAX_BUSY_OVERRIDES", raising=False)
    monkeypatch.delenv("KAFKA_BOOTSTRAP_SERVERS", raising=False)

    settings = load_settings()

    assert settings.bootstrap_servers == "localhost:9092"
    assert (
        settings.monitored_services
        == HealthMonitorEnvironment.DEFAULT_MONITORED_SERVICES
    )
    assert settings.heartbeat_timeout_seconds == 120
    assert settings.startup_grace_seconds == 180
    assert settings.check_interval_seconds == 10
    assert settings.max_busy_seconds == 5400
    assert settings.busy_limit_overrides == {}


def test_load_settings_reads_services_and_timing(monkeypatch):
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker:9093")
    monkeypatch.setenv(
        "HEALTH_MONITORED_SERVICES",
        "core, uploader, notifications, downloader_current, downloader_reference",
    )
    monkeypatch.setenv("HEALTH_HEARTBEAT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("HEALTH_STARTUP_GRACE_SECONDS", "90")
    monkeypatch.setenv("HEALTH_CHECK_INTERVAL_SECONDS", "5")
    monkeypatch.setenv("HEALTH_MAX_BUSY_SECONDS", "7200")
    monkeypatch.setenv("HEALTH_MAX_BUSY_OVERRIDES", "core=600, notifications=120")

    settings = load_settings()

    assert settings.bootstrap_servers == "broker:9093"
    assert settings.monitored_services == (
        "core",
        "uploader",
        "notifications",
        "downloader_current",
        "downloader_reference",
    )
    assert settings.heartbeat_timeout_seconds == 45
    assert settings.startup_grace_seconds == 90
    assert settings.check_interval_seconds == 5
    assert settings.max_busy_seconds == 7200
    assert settings.busy_limit_overrides == {"core": 600, "notifications": 120}


@pytest.mark.parametrize("value", ["0", "-3", "invalid"])
def test_load_settings_rejects_invalid_intervals(monkeypatch, value):
    monkeypatch.setenv("HEALTH_CHECK_INTERVAL_SECONDS", value)

    with pytest.raises(ValueError, match="HEALTH_CHECK_INTERVAL_SECONDS"):
        load_settings()


def test_load_settings_rejects_empty_service_list(monkeypatch):
    monkeypatch.setenv("HEALTH_MONITORED_SERVICES", " , , ")

    with pytest.raises(ValueError, match="at least one service"):
        load_settings()


@pytest.mark.parametrize("value", ["0", "-3", "invalid"])
def test_load_settings_rejects_invalid_busy_timeout(monkeypatch, value):
    monkeypatch.setenv("HEALTH_MAX_BUSY_SECONDS", value)

    with pytest.raises(ValueError, match="HEALTH_MAX_BUSY_SECONDS"):
        load_settings()


@pytest.mark.parametrize("value", ["core=0", "core=-3", "core=invalid", "core"])
def test_load_settings_rejects_invalid_busy_overrides(monkeypatch, value):
    monkeypatch.setenv("HEALTH_MAX_BUSY_OVERRIDES", value)

    with pytest.raises(ValueError, match="HEALTH_MAX_BUSY_OVERRIDES"):
        load_settings()


def test_load_settings_rejects_busy_override_for_unmonitored_service(monkeypatch):
    monkeypatch.setenv("HEALTH_MONITORED_SERVICES", "core")
    monkeypatch.setenv("HEALTH_MAX_BUSY_OVERRIDES", "uploader=120")

    with pytest.raises(ValueError, match="unknown service"):
        load_settings()

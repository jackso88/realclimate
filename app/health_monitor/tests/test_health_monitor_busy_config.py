"""Tests for the stuck-worker limits in the health monitor settings."""

import pytest

from app.health_monitor.config import load_settings


def test_limit_defaults_to_ninety_minutes_without_overrides(clean_environment):
    settings = load_settings()

    assert settings.max_busy_seconds == 5400
    assert settings.busy_limit_overrides == {}


def test_global_limit_can_be_configured(clean_environment):
    clean_environment["HEALTH_MAX_BUSY_SECONDS"] = "900"

    assert load_settings().max_busy_seconds == 900


@pytest.mark.parametrize("value", ["0", "-1", "soon", "1.5"])
def test_global_limit_must_be_a_positive_integer(clean_environment, value):
    clean_environment["HEALTH_MAX_BUSY_SECONDS"] = value

    with pytest.raises(ValueError, match="HEALTH_MAX_BUSY_SECONDS"):
        load_settings()


def test_per_service_overrides_are_parsed(clean_environment):
    clean_environment["HEALTH_MAX_BUSY_OVERRIDES"] = "core=600, notifications_bot = 120"

    settings = load_settings()

    assert settings.busy_limit_overrides == {"core": 600, "notifications_bot": 120}


def test_empty_override_entries_are_ignored(clean_environment):
    clean_environment["HEALTH_MAX_BUSY_OVERRIDES"] = ",core=600,,"

    assert load_settings().busy_limit_overrides == {"core": 600}


@pytest.mark.parametrize("entry", ["core", "core=", "core=abc", "core=0", "core=-5"])
def test_malformed_override_entries_are_rejected(clean_environment, entry):
    clean_environment["HEALTH_MAX_BUSY_OVERRIDES"] = entry

    with pytest.raises(ValueError, match="service=seconds"):
        load_settings()


def test_an_override_for_an_unknown_service_is_rejected(clean_environment):
    clean_environment["HEALTH_MAX_BUSY_OVERRIDES"] = "cor=600"

    with pytest.raises(ValueError, match="unknown service 'cor'"):
        load_settings()


def test_overrides_may_only_name_monitored_services(clean_environment):
    clean_environment["HEALTH_MONITORED_SERVICES"] = "core,uploader"
    clean_environment["HEALTH_MAX_BUSY_OVERRIDES"] = "notifications_bot=120"

    with pytest.raises(ValueError, match="unknown service 'notifications_bot'"):
        load_settings()

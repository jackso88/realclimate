"""Tests for the stuck-worker limits in the health monitor settings."""

import os
from unittest.mock import patch

import pytest

from app.health_monitor.config import load_settings


@pytest.fixture
def environment():
    """Run each test with an empty environment that is restored afterwards."""
    with patch.dict(os.environ, {}, clear=True):
        yield os.environ


def test_limit_defaults_to_ninety_minutes_without_overrides(environment):
    settings = load_settings()

    assert settings.max_busy_seconds == 5400
    assert settings.busy_limit_overrides == {}


def test_global_limit_can_be_configured(environment):
    environment["HEALTH_MAX_BUSY_SECONDS"] = "900"

    assert load_settings().max_busy_seconds == 900


@pytest.mark.parametrize("value", ["0", "-1", "soon", "1.5"])
def test_global_limit_must_be_a_positive_integer(environment, value):
    environment["HEALTH_MAX_BUSY_SECONDS"] = value

    with pytest.raises(ValueError, match="HEALTH_MAX_BUSY_SECONDS"):
        load_settings()


def test_per_service_overrides_are_parsed(environment):
    environment["HEALTH_MAX_BUSY_OVERRIDES"] = "core=600, notifications = 120"

    settings = load_settings()

    assert settings.busy_limit_overrides == {"core": 600, "notifications": 120}


def test_empty_override_entries_are_ignored(environment):
    environment["HEALTH_MAX_BUSY_OVERRIDES"] = ",core=600,,"

    assert load_settings().busy_limit_overrides == {"core": 600}


@pytest.mark.parametrize("entry", ["core", "core=", "core=abc", "core=0", "core=-5"])
def test_malformed_override_entries_are_rejected(environment, entry):
    environment["HEALTH_MAX_BUSY_OVERRIDES"] = entry

    with pytest.raises(ValueError, match="service=seconds"):
        load_settings()


def test_an_override_for_an_unknown_service_is_rejected(environment):
    environment["HEALTH_MAX_BUSY_OVERRIDES"] = "cor=600"

    with pytest.raises(ValueError, match="unknown service 'cor'"):
        load_settings()


def test_overrides_may_only_name_monitored_services(environment):
    environment["HEALTH_MONITORED_SERVICES"] = "core,uploader"
    environment["HEALTH_MAX_BUSY_OVERRIDES"] = "notifications=120"

    with pytest.raises(ValueError, match="unknown service 'notifications'"):
        load_settings()

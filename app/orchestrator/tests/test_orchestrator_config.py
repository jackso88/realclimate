"""Tests for orchestrator environment configuration."""

from types import SimpleNamespace

import pytest

from app.orchestrator import config
from app.orchestrator.config import _positive_int, load_settings
from app.orchestrator.models import OrchestratorSettings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test without orchestrator variables from the host."""
    for name in (
        "DOWNLOAD_TIMEOUT_SECONDS",
        "IMPORT_TIMEOUT_SECONDS",
        "ORCHESTRATOR_INSTANCE_ID",
        "TEST_POSITIVE_INT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_positive_int_returns_the_default_when_unset():
    assert _positive_int("TEST_POSITIVE_INT", 7) == 7


def test_positive_int_parses_a_configured_value(monkeypatch):
    monkeypatch.setenv("TEST_POSITIVE_INT", "42")

    assert _positive_int("TEST_POSITIVE_INT", 7) == 42


@pytest.mark.parametrize("value", ["0", "-5", "abc", "1.5", ""])
def test_positive_int_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("TEST_POSITIVE_INT", value)

    with pytest.raises(ValueError, match="TEST_POSITIVE_INT must be a positive"):
        _positive_int("TEST_POSITIVE_INT", 7)


def test_load_settings_defaults_and_hostname_identity(monkeypatch):
    monkeypatch.setattr(config, "socket", SimpleNamespace(gethostname=lambda: "host-1"))

    settings = load_settings()

    assert settings == OrchestratorSettings(
        request_timeout_seconds=900,
        uploader_timeout_seconds=1800,
        instance_id="host-1",
    )


def test_load_settings_reads_overrides(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("IMPORT_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("ORCHESTRATOR_INSTANCE_ID", "orchestrator-b")

    settings = load_settings()

    assert settings.request_timeout_seconds == 60
    assert settings.uploader_timeout_seconds == 120
    assert settings.instance_id == "orchestrator-b"


def test_load_settings_names_the_invalid_variable(monkeypatch):
    monkeypatch.setenv("IMPORT_TIMEOUT_SECONDS", "never")

    with pytest.raises(ValueError, match="IMPORT_TIMEOUT_SECONDS"):
        load_settings()

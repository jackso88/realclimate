"""Tests for orchestrator environment configuration."""

from types import SimpleNamespace

import pytest

from app.orchestrator import models
from app.orchestrator.config import load_settings
from app.orchestrator.models import OrchestratorSettings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Start every test without orchestrator variables from the host."""
    for name in (
        "DOWNLOAD_TIMEOUT_SECONDS",
        "IMPORT_TIMEOUT_SECONDS",
        "ORCHESTRATOR_INSTANCE_ID",
        "ORCHESTRATOR_POLL_INTERVAL_MARGIN_SECONDS",
        "KAFKA_BOOTSTRAP_SERVERS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_settings_defaults_and_hostname_identity(monkeypatch):
    monkeypatch.setattr(models, "socket", SimpleNamespace(gethostname=lambda: "host-1"))

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

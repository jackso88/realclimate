"""Tests for admin authentication configuration."""

import pytest

from app.admin_auth.config import load_settings
from app.admin_auth.exceptions import AdminLoginError


@pytest.fixture
def required_auth_environment(monkeypatch):
    values = {
        "TAPTOP_BASE_URL": "https://admin.invalid",
        "TAPTOP_CMS_URL": "https://admin.invalid/cms",
        "TAPTOP_USERNAME": "test-user",
        "TAPTOP_PASSWORD": "test-password",
        "TAPTOP_ACCESS": "test-access",
        "TAPTOP_VER_ID": "123",
        "TAPTOP_DESIGN_ID": "456",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS", raising=False)


def test_load_settings_uses_default_cache_ttl(required_auth_environment):
    settings = load_settings()

    assert settings.session_cache_ttl_seconds == 14400
    assert settings.ver_id == 123
    assert settings.design_id == 456


def test_load_settings_reads_custom_cache_ttl(required_auth_environment, monkeypatch):
    monkeypatch.setenv("ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS", "75")

    settings = load_settings()

    assert settings.session_cache_ttl_seconds == 75


@pytest.mark.parametrize("value", ["0", "-1", "invalid"])
def test_load_settings_rejects_invalid_cache_ttl(
    required_auth_environment, monkeypatch, value
):
    monkeypatch.setenv("ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS", value)

    with pytest.raises(AdminLoginError, match="ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS"):
        load_settings()

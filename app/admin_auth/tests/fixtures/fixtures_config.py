"""Fixtures for the admin authentication settings tests."""

import pytest

REQUIRED = {
    "TAPTOP_BASE_URL": "https://admin.invalid/",
    "TAPTOP_CMS_URL": "https://admin.invalid/cms/",
    "TAPTOP_USERNAME": "test-user",
    "TAPTOP_PASSWORD": "test-password",
    "TAPTOP_ACCESS": "test-access",
    "TAPTOP_VER_ID": "123",
    "TAPTOP_DESIGN_ID": "456",
}
OPTIONAL = (
    "ADMIN_AUTH_SESSION_CACHE_TTL_SECONDS",
    "TAPTOP_LOGIN_PATH",
    "TAPTOP_MOSAIC_PATH",
    "TAPTOP_FORM_NAME",
    "TAPTOP_USERNAME_FIELD",
    "TAPTOP_PASSWORD_FIELD",
)


@pytest.fixture
def admin_required_environment(monkeypatch):
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


@pytest.fixture
def admin_isolated_environment(monkeypatch):
    """Start from a clean slate and make sure nothing leaks out of a test."""
    for name in (*REQUIRED, *OPTIONAL):
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


@pytest.fixture
def admin_valid_environment(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)

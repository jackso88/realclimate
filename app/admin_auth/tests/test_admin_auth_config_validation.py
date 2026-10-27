"""Tests for admin_auth settings validation and optional overrides."""

import pytest

from app.admin_auth.config import load_settings
from app.admin_auth.exceptions import AdminLoginError
from app.admin_auth.models import AdminSettings
from app.admin_auth.tests.fixtures.fixtures_config import REQUIRED

pytestmark = pytest.mark.usefixtures("admin_isolated_environment")


def test_defaults_are_applied_to_the_optional_settings(admin_valid_environment):
    settings = load_settings()

    assert settings == AdminSettings(
        base_url="https://admin.invalid",
        cms_url="https://admin.invalid/cms",
        username="test-user",
        password="test-password",
        access="test-access",
        ver_id=123,
        design_id=456,
        session_cache_ttl_seconds=14400,
        login_path="/login",
        mosaic_path="/mosaic",
        form_name="login_form",
        username_field="email",
        password_field="password",
    )


def test_trailing_slashes_are_stripped_from_both_urls(admin_valid_environment):
    settings = load_settings()

    assert not settings.base_url.endswith("/")
    assert not settings.cms_url.endswith("/")


def test_login_form_details_can_be_overridden(admin_valid_environment, monkeypatch):
    monkeypatch.setenv("TAPTOP_LOGIN_PATH", "/sign-in")
    monkeypatch.setenv("TAPTOP_MOSAIC_PATH", "/panel")
    monkeypatch.setenv("TAPTOP_FORM_NAME", "custom_form")
    monkeypatch.setenv("TAPTOP_USERNAME_FIELD", "login")
    monkeypatch.setenv("TAPTOP_PASSWORD_FIELD", "pass")

    settings = load_settings()

    assert settings.login_path == "/sign-in"
    assert settings.mosaic_path == "/panel"
    assert settings.form_name == "custom_form"
    assert settings.username_field == "login"
    assert settings.password_field == "pass"


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_each_required_setting_is_enforced(
    admin_valid_environment, monkeypatch, missing
):
    monkeypatch.delenv(missing)

    with pytest.raises(AdminLoginError, match=missing):
        load_settings()


def test_every_missing_setting_is_listed_in_one_error():
    with pytest.raises(AdminLoginError) as error:
        load_settings()

    for name in REQUIRED:
        assert name in str(error.value)


@pytest.mark.parametrize("name", ["TAPTOP_VER_ID", "TAPTOP_DESIGN_ID"])
def test_numeric_identifiers_must_be_integers(
    admin_valid_environment, monkeypatch, name
):
    monkeypatch.setenv(name, "twelve")

    with pytest.raises(AdminLoginError, match="must be integers"):
        load_settings()

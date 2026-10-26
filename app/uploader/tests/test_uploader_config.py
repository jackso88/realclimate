"""Tests for uploader CMS settings loading."""

import pytest

from app.uploader.config import load_settings
from app.uploader.exceptions import UploaderConfigurationError
from app.uploader.models import Settings
from app.uploader.tests.fixtures.fixtures_config import REQUIRED

pytestmark = pytest.mark.usefixtures("uploader_isolated_environment")


def test_load_settings_builds_immutable_settings(uploader_cms_environment):
    settings = load_settings()

    assert settings == Settings(
        ver_id=7,
        access="u%3B123",
        shop_id=5,
        cms_url="https://cms.example/-/cms/v1",
    )


def test_trailing_slash_is_removed_from_the_cms_url(uploader_cms_environment):
    settings = load_settings()

    assert not settings.cms_url.endswith("/")


@pytest.mark.parametrize("missing", REQUIRED)
def test_each_required_setting_is_enforced(
    uploader_cms_environment, monkeypatch, missing
):
    monkeypatch.delenv(missing)

    with pytest.raises(UploaderConfigurationError, match=missing):
        load_settings()


def test_all_missing_settings_are_reported_together():
    with pytest.raises(UploaderConfigurationError) as error:
        load_settings()

    for name in REQUIRED:
        assert name in str(error.value)


@pytest.mark.parametrize("url", ["ftp://cms.example", "cms.example/api", "//cms"])
def test_cms_url_needs_an_http_scheme(uploader_cms_environment, monkeypatch, url):
    monkeypatch.setenv("TAPTOP_CMS_URL", url)

    with pytest.raises(UploaderConfigurationError, match="http:// or https://"):
        load_settings()


@pytest.mark.parametrize("name", ["TAPTOP_SHOP_ID", "TAPTOP_VER_ID"])
def test_numeric_identifiers_must_be_integers(
    uploader_cms_environment, monkeypatch, name
):
    monkeypatch.setenv(name, "not-a-number")

    with pytest.raises(UploaderConfigurationError, match="must be integers"):
        load_settings()


def test_http_cms_urls_are_accepted(uploader_cms_environment, monkeypatch):
    monkeypatch.setenv("TAPTOP_CMS_URL", "http://localhost:8080/cms")

    settings = load_settings()

    assert settings.cms_url == "http://localhost:8080/cms"

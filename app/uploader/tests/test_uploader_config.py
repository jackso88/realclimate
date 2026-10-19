"""Tests for uploader CMS settings loading."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from app.uploader import config
from app.uploader.config import load_settings
from app.uploader.exceptions import UploaderConfigurationError
from app.uploader.models import Settings

REQUIRED = ("TAPTOP_CMS_URL", "TAPTOP_SHOP_ID", "TAPTOP_VER_ID", "TAPTOP_ACCESS")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """Remove the CMS variables and make sure nothing leaks out of a test."""
    for name in REQUIRED:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


@pytest.fixture
def cms_environment(monkeypatch):
    values = {
        "TAPTOP_CMS_URL": "https://cms.example/-/cms/v1/",
        "TAPTOP_SHOP_ID": "5",
        "TAPTOP_VER_ID": "7",
        "TAPTOP_ACCESS": "u%3B123",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return values


def test_load_settings_builds_immutable_settings(cms_environment):
    settings = load_settings(env_file="/path/that/does/not/exist")

    assert settings == Settings(
        ver_id=7,
        access="u%3B123",
        shop_id=5,
        cms_url="https://cms.example/-/cms/v1",
    )


def test_trailing_slash_is_removed_from_the_cms_url(cms_environment):
    settings = load_settings(env_file="/path/that/does/not/exist")

    assert not settings.cms_url.endswith("/")


@pytest.mark.parametrize("missing", REQUIRED)
def test_each_required_setting_is_enforced(cms_environment, monkeypatch, missing):
    monkeypatch.delenv(missing)

    with pytest.raises(UploaderConfigurationError, match=missing):
        load_settings(env_file="/path/that/does/not/exist")


def test_all_missing_settings_are_reported_together():
    with pytest.raises(UploaderConfigurationError) as error:
        load_settings(env_file="/path/that/does/not/exist")

    for name in REQUIRED:
        assert name in str(error.value)


@pytest.mark.parametrize("url", ["ftp://cms.example", "cms.example/api", "//cms"])
def test_cms_url_needs_an_http_scheme(cms_environment, monkeypatch, url):
    monkeypatch.setenv("TAPTOP_CMS_URL", url)

    with pytest.raises(UploaderConfigurationError, match="http:// or https://"):
        load_settings(env_file="/path/that/does/not/exist")


@pytest.mark.parametrize("name", ["TAPTOP_SHOP_ID", "TAPTOP_VER_ID"])
def test_numeric_identifiers_must_be_integers(cms_environment, monkeypatch, name):
    monkeypatch.setenv(name, "not-a-number")

    with pytest.raises(UploaderConfigurationError, match="must be integers"):
        load_settings(env_file="/path/that/does/not/exist")


def test_http_cms_urls_are_accepted(cms_environment, monkeypatch):
    monkeypatch.setenv("TAPTOP_CMS_URL", "http://localhost:8080/cms")

    settings = load_settings(env_file="/path/that/does/not/exist")

    assert settings.cms_url == "http://localhost:8080/cms"


def test_default_env_file_is_the_dotenv_in_the_repository_root(monkeypatch):
    loader = Mock()
    monkeypatch.setattr(config, "load_dotenv", loader)

    with pytest.raises(UploaderConfigurationError):
        load_settings()

    path = Path(loader.call_args.kwargs["dotenv_path"])
    assert path.name == ".env"
    assert (path.parent / "app" / "uploader").is_dir()
    assert loader.call_args.kwargs["override"] is False

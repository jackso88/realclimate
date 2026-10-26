"""Validation tests for the current downloader's CMS settings."""

import os
from unittest.mock import patch

import pytest

from app.downloader.current.config import load_settings
from app.downloader.current.exceptions import ConfigurationError

VALID = {
    "TAPTOP_CMS_URL": "https://cms.example.test/",
    "TAPTOP_SHOP_ID": "23",
    "TAPTOP_VER_ID": "45",
    "TAPTOP_ACCESS": "access-test",
}


@pytest.fixture
def environment():
    """Run each test with an empty environment that is restored afterwards."""
    with patch.dict(os.environ, {}, clear=True):
        yield os.environ


def test_access_value_is_kept_verbatim(environment):
    environment.update(VALID)

    settings = load_settings()

    assert settings.access == "access-test"


@pytest.mark.parametrize("missing", sorted(VALID))
def test_each_required_setting_is_enforced(environment, missing):
    environment.update(VALID)
    del environment[missing]

    with pytest.raises(ConfigurationError, match=missing):
        load_settings()


def test_every_missing_setting_is_listed_in_one_error(environment):
    with pytest.raises(ConfigurationError) as error:
        load_settings()

    for name in VALID:
        assert name in str(error.value)


@pytest.mark.parametrize("url", ["ftp://cms.example", "cms.example", "/relative"])
def test_cms_url_needs_an_http_scheme(environment, url):
    environment.update(VALID)
    environment["TAPTOP_CMS_URL"] = url

    with pytest.raises(ConfigurationError, match="http:// or https://"):
        load_settings()


@pytest.mark.parametrize("name", ["TAPTOP_SHOP_ID", "TAPTOP_VER_ID"])
def test_numeric_identifiers_must_be_integers(environment, name):
    environment.update(VALID)
    environment[name] = "twenty"

    with pytest.raises(ConfigurationError, match=f"{name} must be an integer"):
        load_settings()


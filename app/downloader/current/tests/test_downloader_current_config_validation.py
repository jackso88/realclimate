"""Validation tests for the current downloader's CMS settings."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.downloader.current import config
from app.downloader.current.config import load_settings
from app.downloader.current.exceptions import ConfigurationError

VALID = {
    "TAPTOP_CMS_URL": "https://cms.example.test/",
    "TAPTOP_SHOP_ID": "23",
    "TAPTOP_VER_ID": "45",
    "TAPTOP_ACCESS": "access-test",
}
MISSING_FILE = "/missing/.env"


@pytest.fixture
def environment():
    """Run each test with an empty environment that is restored afterwards."""
    with patch.dict(os.environ, {}, clear=True):
        yield os.environ


def test_access_value_is_kept_verbatim(environment):
    environment.update(VALID)

    settings = load_settings(env_file=MISSING_FILE)

    assert settings.access == "access-test"


@pytest.mark.parametrize("missing", sorted(VALID))
def test_each_required_setting_is_enforced(environment, missing):
    environment.update(VALID)
    del environment[missing]

    with pytest.raises(ConfigurationError, match=missing):
        load_settings(env_file=MISSING_FILE)


def test_every_missing_setting_is_listed_in_one_error(environment):
    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file=MISSING_FILE)

    for name in VALID:
        assert name in str(error.value)


@pytest.mark.parametrize("url", ["ftp://cms.example", "cms.example", "/relative"])
def test_cms_url_needs_an_http_scheme(environment, url):
    environment.update(VALID)
    environment["TAPTOP_CMS_URL"] = url

    with pytest.raises(ConfigurationError, match="http:// or https://"):
        load_settings(env_file=MISSING_FILE)


@pytest.mark.parametrize("name", ["TAPTOP_SHOP_ID", "TAPTOP_VER_ID"])
def test_numeric_identifiers_must_be_integers(environment, name):
    environment.update(VALID)
    environment[name] = "twenty"

    with pytest.raises(ConfigurationError, match=f"{name} must be an integer"):
        load_settings(env_file=MISSING_FILE)


def test_values_come_from_the_env_file_without_overriding_the_process(
    environment, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TAPTOP_CMS_URL=https://from-file.example\n"
        "TAPTOP_SHOP_ID=1\n"
        "TAPTOP_VER_ID=2\n"
        "TAPTOP_ACCESS=from-file\n",
        encoding="utf-8",
    )
    environment["TAPTOP_ACCESS"] = "from-process"

    settings = load_settings(env_file=env_file)

    assert settings.cms_url == "https://from-file.example"
    assert settings.shop_id == 1
    assert settings.access == "from-process"


def test_default_env_file_is_the_dotenv_in_the_repository_root(
    environment, monkeypatch
):
    loader = Mock()
    monkeypatch.setattr(config, "load_dotenv", loader)

    with pytest.raises(ConfigurationError):
        load_settings()

    path = Path(loader.call_args.kwargs["dotenv_path"])
    assert path.name == ".env"
    assert (path.parent / "app" / "downloader" / "current").is_dir()
    assert loader.call_args.kwargs["override"] is False

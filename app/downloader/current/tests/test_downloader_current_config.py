"""Configuration tests for the current downloader service."""

import os
from unittest.mock import patch

import pytest

from app.downloader.current.config import load_settings


@patch.dict(
    os.environ,
    {
        "TAPTOP_CMS_URL": "https://cms.example.test/",
        "TAPTOP_SHOP_ID": "23",
        "TAPTOP_VER_ID": "45",
        "TAPTOP_ACCESS": "access-test",
    },
    clear=True,
)
def test_loads_only_export_service_settings():
    settings = load_settings(env_file="/missing/.env")
    assert settings.cms_url == "https://cms.example.test"
    assert settings.shop_id == 23
    assert settings.ver_id == 45

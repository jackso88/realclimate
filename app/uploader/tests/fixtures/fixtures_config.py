"""Fixtures for the uploader settings tests."""

import pytest

REQUIRED = ("TAPTOP_CMS_URL", "TAPTOP_SHOP_ID", "TAPTOP_VER_ID", "TAPTOP_ACCESS")


@pytest.fixture
def uploader_isolated_environment(monkeypatch):
    """Remove the CMS variables and make sure nothing leaks out of a test."""
    for name in REQUIRED:
        monkeypatch.setenv(name, "placeholder")
        monkeypatch.delenv(name)


@pytest.fixture
def uploader_cms_environment(monkeypatch):
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

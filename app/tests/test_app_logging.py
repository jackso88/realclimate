"""Contract tests for the console logging every service configures."""

import importlib
import logging
from unittest.mock import Mock

import pytest

CONFIG_MODULES = [
    "app.admin_auth.config",
    "app.core.config",
    "app.downloader.current.config",
    "app.downloader.reference.config",
    "app.health_monitor.config",
    "app.notifications.bot.config",
    "app.scheduler.config",
    "app.uploader.config",
]
EXPECTED_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
EXPECTED_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture
def basic_config(monkeypatch):
    """Intercept logging.basicConfig so tests never reconfigure real logging."""
    mock = Mock()
    monkeypatch.setattr(logging, "basicConfig", mock)
    return mock


@pytest.mark.parametrize("module_name", CONFIG_MODULES)
def test_every_service_logs_in_the_same_console_format(module_name, basic_config):
    module = importlib.import_module(module_name)

    module.configure_logging()

    basic_config.assert_called_once_with(
        level=logging.INFO,
        format=EXPECTED_FORMAT,
        datefmt=EXPECTED_DATE_FORMAT,
    )


@pytest.mark.parametrize("module_name", CONFIG_MODULES)
def test_every_service_allows_a_custom_log_level(module_name, basic_config):
    module = importlib.import_module(module_name)

    module.configure_logging(logging.DEBUG)

    assert basic_config.call_args.kwargs["level"] == logging.DEBUG

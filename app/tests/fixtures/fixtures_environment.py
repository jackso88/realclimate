"""Shared environment fixtures."""

import os
from unittest.mock import patch

import pytest


@pytest.fixture
def clean_environment():
    """Run each test with an empty environment that is restored afterwards."""
    with patch.dict(os.environ, {}, clear=True):
        yield os.environ

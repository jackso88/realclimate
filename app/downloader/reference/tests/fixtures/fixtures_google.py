"""Fixtures for the reference downloader Google OAuth tests."""

import pytest


@pytest.fixture
def reference_oauth_files(tmp_path):
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    return credentials_file, token_file

import pytest


@pytest.fixture(scope="session")
def token():
    return "123456789:AAFakeTokenValue"


@pytest.fixture(scope="session")
def token_url(token):
    return f"https://api.telegram.org/bot{token}/sendMessage"

"""Tests for removing credentials from error text before it is shown or sent."""

import pytest

from app.messaging.kafka import sanitize_error

TELEGRAM_URL = "https://api.telegram.org/bot123456789:AAFake-Token_Value/sendMessage"


def test_telegram_bot_token_in_an_api_url_is_redacted():
    message = f"400 Client Error: Bad Request for url: {TELEGRAM_URL}"

    cleaned = sanitize_error(message)

    assert "AAFake-Token_Value" not in cleaned
    assert "123456789" not in cleaned
    assert cleaned.endswith("https://api.telegram.org/bot<redacted>/sendMessage")


def test_the_redaction_is_case_insensitive():
    cleaned = sanitize_error("url: /BOT123456789:AAFakeTokenValue/getMe")

    assert "AAFakeTokenValue" not in cleaned


@pytest.mark.parametrize("name", ["access", "token", "password", "ACCESS"])
def test_credential_query_parameters_are_still_redacted(name):
    cleaned = sanitize_error(f"GET https://cms.example/?x=1&{name}=s3cret&y=2")

    assert "s3cret" not in cleaned
    assert "x=1" in cleaned
    assert "y=2" in cleaned


def test_both_kinds_of_secret_in_one_message_are_redacted():
    message = f"{TELEGRAM_URL}?access=u%3Bsecret"

    cleaned = sanitize_error(message)

    assert "AAFake" not in cleaned
    assert "u%3Bsecret" not in cleaned


@pytest.mark.parametrize(
    "message",
    [
        "Connection refused",
        "robot2000: ready",
        "https://api.telegram.org/getMe",
        "",
    ],
)
def test_ordinary_text_is_left_alone(message):
    assert sanitize_error(message) == message

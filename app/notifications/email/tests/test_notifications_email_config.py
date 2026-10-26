"""Tests for email service settings validation and loading."""

import pytest
from pydantic import ValidationError

from app.notifications.email.config import load_settings
from app.notifications.email.models import EmailSettings


def test_load_settings_reads_the_process_environment(set_email_env):
    settings = load_settings()

    assert settings.bootstrap_servers == "kafka:9092"
    assert settings.smtp_host == "smtp.example.invalid"
    assert settings.smtp_port == 587
    assert settings.smtp_security == "starttls"
    assert settings.smtp_username == "mailer"
    assert settings.smtp_password.get_secret_value() == "s3cret-pass"
    assert settings.smtp_timeout_seconds == 5
    assert settings.sender == "notifications@example.invalid"
    assert settings.recipients == ["first@example.invalid", "second@example.invalid"]


def test_load_settings_fails_fast_when_required_variables_are_missing(monkeypatch):
    for name in ("EMAIL_SMTP_HOST", "EMAIL_SENDER", "EMAIL_RECIPIENTS"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError):
        load_settings()


def test_defaults_apply_to_optional_variables(email_env):
    for name in (
        "KAFKA_BOOTSTRAP_SERVERS",
        "EMAIL_SMTP_PORT",
        "EMAIL_SMTP_SECURITY",
        "EMAIL_SMTP_USERNAME",
        "EMAIL_SMTP_PASSWORD",
        "EMAIL_SMTP_TIMEOUT_SECONDS",
    ):
        email_env.pop(name)

    settings = EmailSettings.model_validate(email_env)

    assert settings.bootstrap_servers == "localhost:9092"
    assert settings.smtp_port == 587
    assert settings.smtp_security == "starttls"
    assert settings.smtp_username is None
    assert settings.smtp_password is None
    assert settings.smtp_timeout_seconds == 15


def test_blank_credentials_mean_no_authentication(make_email_settings):
    settings = make_email_settings(EMAIL_SMTP_USERNAME="", EMAIL_SMTP_PASSWORD="  ")

    assert settings.smtp_username is None
    assert settings.smtp_password is None


def test_recipients_are_split_and_stripped(make_email_settings):
    settings = make_email_settings(EMAIL_RECIPIENTS=" a@x.invalid , b@y.invalid ")

    assert settings.recipients == ["a@x.invalid", "b@y.invalid"]


@pytest.mark.parametrize(
    "recipients",
    [
        ["only@one.invalid"],
        ["a@x.invalid", "b@y.invalid", "c@z.invalid"],
        [f"user{number}@x.invalid" for number in range(10)],
    ],
)
def test_any_positive_number_of_recipients_is_allowed(make_email_settings, recipients):
    settings = make_email_settings(EMAIL_RECIPIENTS=",".join(recipients))

    assert settings.recipients == recipients


def test_empty_recipient_list_is_rejected_with_a_clear_message(make_email_settings):
    with pytest.raises(ValidationError, match="at least one address"):
        make_email_settings(EMAIL_RECIPIENTS="")


def test_recipients_accept_an_already_split_list(make_email_settings):
    settings = make_email_settings(EMAIL_RECIPIENTS=["a@x.invalid", "b@y.invalid"])

    assert settings.recipients == ["a@x.invalid", "b@y.invalid"]


def test_settings_can_be_built_with_field_names(email_settings):
    clone = EmailSettings(
        smtp_host="mail.example.invalid",
        sender=email_settings.sender,
        recipients=email_settings.recipients,
    )

    assert clone.smtp_host == "mail.example.invalid"


def test_password_is_hidden_from_representations(email_settings):
    assert "s3cret-pass" not in repr(email_settings)
    assert "s3cret-pass" not in str(email_settings.smtp_password)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("EMAIL_SMTP_HOST", ""),
        ("EMAIL_SMTP_PORT", "0"),
        ("EMAIL_SMTP_PORT", "70000"),
        ("EMAIL_SMTP_PORT", "abc"),
        ("EMAIL_SMTP_SECURITY", "plaintext"),
        ("EMAIL_SMTP_TIMEOUT_SECONDS", "0"),
        ("EMAIL_SENDER", "not-an-address"),
        ("EMAIL_RECIPIENTS", ""),
        ("EMAIL_RECIPIENTS", " , "),
        ("EMAIL_RECIPIENTS", "a@x.invalid,broken"),
        ("EMAIL_RECIPIENTS", "a@x.invalid,A@X.invalid"),
        ("KAFKA_BOOTSTRAP_SERVERS", ""),
    ],
)
def test_invalid_values_are_rejected(make_email_settings, name, value):
    with pytest.raises(ValidationError):
        make_email_settings(**{name: value})


@pytest.mark.parametrize("missing", ["EMAIL_SMTP_USERNAME", "EMAIL_SMTP_PASSWORD"])
def test_credentials_must_be_set_together(email_env, missing):
    email_env.pop(missing)

    with pytest.raises(ValidationError, match="set together"):
        EmailSettings.model_validate(email_env)


def test_password_may_be_passed_as_a_secret(email_settings):
    from pydantic import SecretStr

    clone = EmailSettings(
        smtp_host=email_settings.smtp_host,
        sender=email_settings.sender,
        recipients=email_settings.recipients,
        smtp_username="mailer",
        smtp_password=SecretStr("another-secret"),
    )

    assert clone.smtp_password.get_secret_value() == "another-secret"


def test_configure_logging_sets_the_standard_format(monkeypatch):
    from unittest.mock import Mock

    from app.notifications.email import config

    basic_config = Mock()
    monkeypatch.setattr(config.logging, "basicConfig", basic_config)

    config.configure_logging()

    kwargs = basic_config.call_args.kwargs
    assert kwargs["level"] == config.logging.INFO
    assert "%(levelname)s" in kwargs["format"]

"""Fixtures that provide email service settings."""

import pytest

EMAIL_ENV = {
    "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
    "EMAIL_SMTP_HOST": "smtp.example.invalid",
    "EMAIL_SMTP_PORT": "587",
    "EMAIL_SMTP_SECURITY": "starttls",
    "EMAIL_SMTP_USERNAME": "mailer",
    "EMAIL_SMTP_PASSWORD": "s3cret-pass",
    "EMAIL_SMTP_TIMEOUT_SECONDS": "5",
    "EMAIL_SENDER": "notifications@example.invalid",
    "EMAIL_RECIPIENTS": "first@example.invalid,second@example.invalid",
}


@pytest.fixture
def email_env():
    """Return a fresh, valid set of email service environment variables."""
    return dict(EMAIL_ENV)


@pytest.fixture
def email_settings(email_env):
    """Return validated settings built from the valid environment."""
    from app.notifications.email.models import EmailSettings

    return EmailSettings.model_validate(email_env)


@pytest.fixture
def make_email_settings(email_env):
    """Return a factory that builds settings with some variables overridden."""

    from app.notifications.email.models import EmailSettings

    def factory(**overrides):
        return EmailSettings.model_validate({**email_env, **overrides})

    return factory


@pytest.fixture
def set_email_env(monkeypatch, email_env):
    """Put the valid email variables into the process environment."""
    for name, value in email_env.items():
        monkeypatch.setenv(name, value)
    return email_env

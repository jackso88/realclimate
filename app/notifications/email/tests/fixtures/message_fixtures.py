"""Fixtures that provide Kafka envelopes and change reports."""

import pytest


@pytest.fixture
def changes():
    """Return a small realistic change report."""
    return ["New article ABC-1: Desk lamp", "Price changed for ABC-2: 10.00 -> 12.50"]


@pytest.fixture
def detailed_changes_envelope(changes):
    """Return a ``detailed_changes`` envelope carrying a correlation ID."""
    from app.contracts.models import Envelope

    return Envelope.create(
        "detailed_changes", {"changes": changes}, correlation_id="corr-123"
    )


@pytest.fixture
def make_envelope():
    """Return a factory that builds envelopes with a chosen command and payload."""

    from app.contracts.models import Envelope

    def factory(command, payload=None, correlation_id="corr-123"):
        return Envelope.create(command, payload, correlation_id=correlation_id)

    return factory


@pytest.fixture
def notification(changes):
    from app.notifications.email.sender import build_notification

    return build_notification(changes, "corr-123")

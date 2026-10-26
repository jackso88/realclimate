"""Tests for the email service DTOs."""

import pytest
from pydantic import ValidationError

from app.notifications.email.models import DetailedChangesPayload, EmailNotification


def test_payload_keeps_the_reported_changes(changes):
    assert (
        DetailedChangesPayload.model_validate({"changes": changes}).changes == changes
    )


@pytest.mark.parametrize("payload", [{}, {"changes": None}, {"changes": []}])
def test_missing_or_empty_changes_become_an_empty_list(payload):
    assert DetailedChangesPayload.model_validate(payload).changes == []


def test_blank_changes_are_dropped():
    payload = DetailedChangesPayload.model_validate({"changes": ["a", "", "  \n", "b"]})

    assert payload.changes == ["a", "b"]


def test_unknown_payload_keys_are_ignored():
    payload = DetailedChangesPayload.model_validate({"changes": ["a"], "extra": 1})

    assert payload.changes == ["a"]


@pytest.mark.parametrize("changes", ["a string", [1, 2], [["nested"]], {"a": "b"}])
def test_malformed_changes_are_rejected(changes):
    with pytest.raises(ValidationError):
        DetailedChangesPayload.model_validate({"changes": changes})


def test_notification_requires_a_subject_and_a_body():
    with pytest.raises(ValidationError):
        EmailNotification(subject="", body="text")
    with pytest.raises(ValidationError):
        EmailNotification(subject="subject", body="")


def test_notification_correlation_id_is_optional():
    assert EmailNotification(subject="s", body="b").correlation_id is None

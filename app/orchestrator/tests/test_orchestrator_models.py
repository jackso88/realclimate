"""Tests for the orchestrator settings model."""

import pytest

from app.orchestrator.models import OrchestratorSettings


def test_worst_case_run_with_the_default_timeouts_is_75_minutes():
    assert OrchestratorSettings().worst_case_run_seconds == 4500


@pytest.mark.parametrize(
    ("request_timeout", "uploader_timeout", "expected"),
    [(1, 1, 4), (900, 1800, 4500), (60, 0, 180), (1800, 3600, 9000)],
)
def test_worst_case_is_three_requests_plus_the_upload(
    request_timeout, uploader_timeout, expected
):
    settings = OrchestratorSettings(
        request_timeout_seconds=request_timeout,
        uploader_timeout_seconds=uploader_timeout,
    )

    assert settings.worst_case_run_seconds == expected

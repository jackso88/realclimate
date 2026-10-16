"""Tests for the health monitor entry point."""

from unittest.mock import Mock

from app.health_monitor import main as health_main


def test_main_configures_logging_then_runs_the_monitor_with_loaded_settings(
    monkeypatch,
):
    events = []
    settings = object()
    monkeypatch.setattr(
        health_main, "configure_logging", lambda: events.append("logging")
    )
    monkeypatch.setattr(health_main, "load_settings", lambda: settings)
    run = Mock(side_effect=lambda received: events.append(("run", received)))
    monkeypatch.setattr(health_main, "run_health_monitor", run)

    health_main.main()

    assert events == ["logging", ("run", settings)]

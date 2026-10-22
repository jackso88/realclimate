"""Tests for core worker settings loading and logging configuration."""

import logging
import re

import pytest
from pydantic import ValidationError

from app.core.config import configure_logging, load_settings

# --- load_settings --------------------------------------------------------------


def test_load_settings_returns_validated_settings(env, settings_model):
    settings = load_settings()

    assert isinstance(settings, settings_model)
    assert settings.KAFKA_BOOTSTRAP_SERVERS == "kafka:9092"
    assert settings.OUTPUT_DIR == "/data/out"


def test_load_settings_applies_defaults_for_optional_values(env, settings_model):
    assert load_settings().BATCH_SIZE == 100


def test_load_settings_coerces_string_environment_values(env, settings_model):
    env["BATCH_SIZE"] = "250"  # environment values are always strings

    assert load_settings().BATCH_SIZE == 250


def test_load_settings_reads_the_whole_environment(env, settings_model):
    env["UNRELATED"] = "value"

    load_settings()

    assert settings_model.received == env


def test_load_settings_validates_a_copy_of_the_environment(env, settings_model):
    load_settings()

    # A copy guarantees validation can never mutate the live environment.
    assert settings_model.received is not env


def test_load_settings_reflects_environment_changes_between_calls(env, settings_model):
    first = load_settings()
    env["OUTPUT_DIR"] = "/data/other"

    assert first.OUTPUT_DIR == "/data/out"
    assert load_settings().OUTPUT_DIR == "/data/other"


@pytest.mark.parametrize(
    "broken",
    [
        {"OUTPUT_DIR": None},  # required variable missing
        {"KAFKA_BOOTSTRAP_SERVERS": ""},  # violates min_length
        {"BATCH_SIZE": "many"},  # not an integer
        {"BATCH_SIZE": "0"},  # violates gt=0
    ],
)
def test_invalid_settings_raise_value_error(env, settings_model, broken):
    for name, value in broken.items():
        if value is None:
            del env[name]
        else:
            env[name] = value

    with pytest.raises(ValueError, match="^Invalid core settings:") as exc:
        load_settings()

    # pydantic's ValidationError is itself a ValueError subclass, so the type
    # must be checked exactly to prove the error was wrapped.
    assert type(exc.value) is ValueError


def test_error_message_names_the_offending_field(env, settings_model):
    env["BATCH_SIZE"] = "many"

    with pytest.raises(ValueError) as exc:
        load_settings()

    assert "BATCH_SIZE" in str(exc.value)


def test_error_keeps_original_validation_error_as_cause(env, settings_model):
    del env["OUTPUT_DIR"]

    with pytest.raises(ValueError) as exc:
        load_settings()

    assert isinstance(exc.value.__cause__, ValidationError)


def test_empty_environment_reports_every_missing_field(env, settings_model):
    env.clear()

    with pytest.raises(ValueError) as exc:
        load_settings()

    message = str(exc.value)
    assert "KAFKA_BOOTSTRAP_SERVERS" in message
    assert "OUTPUT_DIR" in message


# --- configure_logging ----------------------------------------------------------


def test_default_level_is_info(reset_root_logger):
    root = reset_root_logger()

    configure_logging()

    assert root.level == logging.INFO


@pytest.mark.parametrize("level", [logging.DEBUG, logging.WARNING, logging.ERROR])
def test_custom_level_is_applied(reset_root_logger, level):
    root = reset_root_logger()

    configure_logging(level)

    assert root.level == level


def test_installs_a_single_console_handler(reset_root_logger):
    root = reset_root_logger()

    configure_logging()

    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0], logging.StreamHandler)


def test_handler_uses_expected_format(reset_root_logger):
    root = reset_root_logger()

    configure_logging()

    formatter = root.handlers[0].formatter
    assert formatter._fmt == "%(asctime)s %(levelname)s %(name)s: %(message)s"
    assert formatter.datefmt == "%Y-%m-%d %H:%M:%S"


def test_log_lines_are_written_in_the_service_format(reset_root_logger, capsys):
    reset_root_logger()
    configure_logging()

    logging.getLogger("core.worker").info("started")

    line = capsys.readouterr().err.strip()
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO core\.worker: started", line
    )


def test_messages_below_the_level_are_not_emitted(reset_root_logger, capsys):
    reset_root_logger()
    configure_logging(logging.WARNING)

    logging.getLogger("core.worker").info("hidden")
    logging.getLogger("core.worker").warning("shown")

    output = capsys.readouterr().err
    assert "hidden" not in output
    assert "WARNING core.worker: shown" in output


def test_second_call_does_not_add_another_handler(reset_root_logger):
    root = reset_root_logger()

    configure_logging()
    configure_logging()

    assert len(root.handlers) == 1


def test_second_call_does_not_change_the_level(reset_root_logger):
    # basicConfig is a no-op once the root logger has handlers (no force=True).
    root = reset_root_logger()

    configure_logging(logging.INFO)
    configure_logging(logging.DEBUG)

    assert root.level == logging.INFO


def test_existing_root_handlers_are_left_untouched(reset_root_logger):
    root = reset_root_logger()
    existing = logging.NullHandler()
    root.addHandler(existing)
    root.setLevel(logging.ERROR)

    configure_logging(logging.DEBUG)

    assert root.handlers == [existing]
    assert root.level == logging.ERROR

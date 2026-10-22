"""Fixtures for the core settings and logging tests."""

import logging
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, Field

from app.core import config as settings_module


class FakeCoreSettings(BaseModel):
    """Small stand-in for CoreSettings with one default, one constraint, one coercion."""

    KAFKA_BOOTSTRAP_SERVERS: str = Field(min_length=1)
    OUTPUT_DIR: str
    BATCH_SIZE: int = Field(default=100, gt=0)


@pytest.fixture
def env(monkeypatch) -> dict[str, str]:
    """A fully controlled environment, visible only to the settings module.

    Tests mutate the returned dict; the real os.environ is never touched.
    """
    variables = {
        "KAFKA_BOOTSTRAP_SERVERS": "kafka:9092",
        "OUTPUT_DIR": "/data/out",
    }
    monkeypatch.setattr(settings_module, "os", SimpleNamespace(environ=variables))
    return variables


@pytest.fixture
def settings_model(monkeypatch) -> type[FakeCoreSettings]:
    """Replace CoreSettings in the settings module with a recording fake."""

    class RecordingSettings(FakeCoreSettings):
        received: ClassVar[Any] = None  # last object passed to model_validate

        @classmethod
        def model_validate(cls, obj, *args, **kwargs):
            cls.received = obj
            return super().model_validate(obj, *args, **kwargs)

    monkeypatch.setattr(settings_module, "CoreSettings", RecordingSettings)
    return RecordingSettings


@pytest.fixture
def reset_root_logger():
    """Return a function that gives the test a pristine root logger.

    logging.basicConfig is a no-op when the root logger already has handlers.
    pytest attaches its own capture handlers to the root logger right before the
    test body runs, so the reset must happen inside the test, not in a fixture.
    The original handlers and level are restored after the test.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    def reset() -> logging.Logger:
        root.handlers.clear()
        root.setLevel(logging.WARNING)  # the stdlib default for a fresh root logger
        return root

    yield reset
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)

import pytest
from app.notifications import telegram
from types import SimpleNamespace
from unittest.mock import Mock
from urllib3.connectionpool import HTTPConnectionPool


class FakeNet:
    """A queue for responses/exceptions at the urllib3 network layer, plus call tracking."""

    def __init__(self):
        self.queue = []
        self.requests = 0
        self.sleeps = []
        self.rate_calls = []

    def make_request(self, conn, method, url, **kwargs):
        self.requests += 1
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def post(monkeypatch, token):
    """Replace requests.post.Session with a mock that returns an accepted response."""
    response = Mock()
    response.json.return_value = {"ok": True}
    mock_post = Mock(return_value=response)
    monkeypatch.setattr(telegram.requests.Session, "post", mock_post)
    monkeypatch.setattr(telegram, "acquire_rate_limit", Mock())
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    mock_post.response = response
    return mock_post


@pytest.fixture
def pauses(monkeypatch):
    """Record the pauses between message parts instead of sleeping."""
    delays = []
    monkeypatch.setattr(telegram, "time", SimpleNamespace(sleep=delays.append))
    return delays


@pytest.fixture
def net(monkeypatch):
    """The network is intercepted at the `urllib3` level, so `Retry` functions exactly as it should"""
    fake = FakeNet()
    monkeypatch.setattr(HTTPConnectionPool, "_make_request", fake.make_request)
    monkeypatch.setattr("urllib3.util.retry.time.sleep", fake.sleeps.append)
    monkeypatch.setattr(
        telegram, "acquire_rate_limit", lambda *args: fake.rate_calls.append(args)
    )
    return fake

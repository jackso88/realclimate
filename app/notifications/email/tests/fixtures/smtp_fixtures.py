"""Fixtures that replace ``smtplib`` with an in-memory fake server."""

import pytest

SENDER_SMTPLIB = "app.notifications.email.sender.smtplib"


class FakeSMTPConnection:
    """One fake SMTP session that records every call made on it."""

    def __init__(self, server, kind, host, port, timeout, context=None):
        server.connections.append(self)
        self.server = server
        self.kind = kind
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.calls = []
        self.sent = []
        server.fail_at("connect")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.calls.append("quit")
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.server.fail_at("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))
        self.server.fail_at("login")

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.calls.append("send_message")
        self.server.fail_at("send_message")
        self.sent.append((message, from_addr, to_addrs))
        return self.server.refused


class FakeSMTPServer:
    """Controller shared by all fake connections opened during one test.

    Set ``errors[step] = exception`` to make a step ("connect", "starttls",
    "login" or "send_message") raise, and ``refused`` to the recipient mapping
    that ``send_message`` should report back.
    """

    def __init__(self):
        self.connections = []
        self.errors = {}
        self.refused = {}

    def fail_at(self, step):
        if step in self.errors:
            raise self.errors[step]

    @property
    def connection(self):
        assert len(self.connections) == 1
        return self.connections[0]


@pytest.fixture
def fake_smtp(monkeypatch):
    """Replace ``smtplib.SMTP`` and ``SMTP_SSL`` with in-memory fakes."""
    server = FakeSMTPServer()

    def plain(host, port, timeout=None):
        return FakeSMTPConnection(server, "plain", host, port, timeout)

    def secure(host, port, timeout=None, context=None):
        return FakeSMTPConnection(server, "ssl", host, port, timeout, context)

    monkeypatch.setattr(f"{SENDER_SMTPLIB}.SMTP", plain)
    monkeypatch.setattr(f"{SENDER_SMTPLIB}.SMTP_SSL", secure)
    return server

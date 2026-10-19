"""Tests for the rate-limiter's small RESP2 Redis client."""

from io import BytesIO

import pytest

from app.rate_limiter.redis_client import RedisClient, RedisCommandError


class FakeSocket:
    """Capture Redis commands and return scripted RESP data."""

    def __init__(self, response: bytes) -> None:
        self.reader = BytesIO(response)
        self.sent: list[bytes] = []
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, timeout):
        self.timeout = timeout

    def makefile(self, _mode):
        return self.reader

    def sendall(self, data):
        self.sent.append(data)


def test_from_url_decodes_acl_credentials_and_uses_port_and_database():
    client = RedisClient.from_url(
        "redis://rate-user:p%40ss@redis.internal:6381/4", socket_timeout=2
    )

    assert (client.host, client.port, client.database) == (
        "redis.internal",
        6381,
        4,
    )
    assert (client.username, client.password, client.socket_timeout) == (
        "rate-user",
        "p@ss",
        2,
    )


def test_from_url_defaults_to_port_and_database_zero():
    client = RedisClient.from_url("redis://redis.internal")

    assert (client.host, client.port, client.database) == ("redis.internal", 6379, 0)
    assert client.username is None
    assert client.password is None


@pytest.mark.parametrize(
    "url",
    [
        "http://redis.internal/0",
        "redis:///0",
        "redis://redis.internal/not-a-db",
        "redis://redis.internal/-1",
    ],
)
def test_from_url_rejects_invalid_scheme_host_or_database(url):
    with pytest.raises(ValueError):
        RedisClient.from_url(url)


def test_set_if_absent_authenticates_selects_db_and_sends_set_nx_px(monkeypatch):
    fake_socket = FakeSocket(b"+OK\r\n+OK\r\n+OK\r\n")
    monkeypatch.setattr(
        "app.rate_limiter.redis_client.socket.create_connection",
        lambda address, timeout: fake_socket,
    )
    client = RedisClient("redis.internal", 6381, 3, "user", "secret", socket_timeout=2)

    assert client.set_if_absent("rate-limit:cms", 5500)
    assert fake_socket.timeout == 2
    assert fake_socket.sent == [
        b"*3\r\n$4\r\nAUTH\r\n$4\r\nuser\r\n$6\r\nsecret\r\n",
        b"*2\r\n$6\r\nSELECT\r\n$1\r\n3\r\n",
        b"*6\r\n$3\r\nSET\r\n$14\r\nrate-limit:cms\r\n$1\r\n1\r\n"
        b"$2\r\nNX\r\n$2\r\nPX\r\n$4\r\n5500\r\n",
    ]


def test_set_if_absent_returns_false_for_nil_reply(monkeypatch):
    fake_socket = FakeSocket(b"$-1\r\n")
    monkeypatch.setattr(
        "app.rate_limiter.redis_client.socket.create_connection",
        lambda *_args, **_kwargs: fake_socket,
    )
    client = RedisClient("redis.internal", 6379, 0, None, None)

    assert not client.set_if_absent("bucket", 10)


def test_ttl_reads_pttl_integer_reply(monkeypatch):
    fake_socket = FakeSocket(b":321\r\n")
    monkeypatch.setattr(
        "app.rate_limiter.redis_client.socket.create_connection",
        lambda *_args, **_kwargs: fake_socket,
    )

    assert (
        RedisClient("redis.internal", 6379, 0, None, None).ttl_milliseconds("bucket")
        == 321
    )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"+OK\r\n", "OK"),
        (b":42\r\n", 42),
        (b"$3\r\nabc\r\n", "abc"),
        (b"$-1\r\n", None),
    ],
)
def test_resp2_types_are_decoded(response, expected):
    assert RedisClient._read(BytesIO(response)) == expected


def test_resp_error_is_exposed_as_redis_command_error():
    with pytest.raises(RedisCommandError, match="WRONGTYPE"):
        RedisClient._read(BytesIO(b"-WRONGTYPE invalid operation\r\n"))


@pytest.mark.parametrize(
    "response",
    [
        b"",
        b"+incomplete",
        b"?unsupported\r\n",
        b"$3\r\nab",
    ],
)
def test_incomplete_or_unknown_resp_reply_raises_oserror(response):
    with pytest.raises(OSError):
        RedisClient._read(BytesIO(response))

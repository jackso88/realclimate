"""Tests for the small RESP2 client used by the core Redis input store."""

from io import BytesIO

import pytest

from app.core.redis_client import RedisClient, RedisCommandError


class FakeSocket:
    def __init__(self, response):
        self.reader = BytesIO(response)
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, _timeout):
        pass

    def makefile(self, _mode):
        return self.reader

    def sendall(self, data):
        self.sent.append(data)


def test_redis_url_parses_acl_credentials_and_database():
    client = RedisClient.from_url(
        "redis://worker:p%40ss@redis.internal:6380/3", socket_timeout=2.5
    )

    assert client.host == "redis.internal"
    assert client.port == 6380
    assert client.database == 3
    assert client.username == "worker"
    assert client.password == "p@ss"
    assert client.socket_timeout == 2.5


@pytest.mark.parametrize("url", ["http://redis/0", "redis:///0", "redis://host/-1"])
def test_invalid_redis_url_is_rejected(url):
    with pytest.raises(ValueError):
        RedisClient.from_url(url)


def test_execute_command_authenticates_selects_database_and_encodes_bytes(monkeypatch):
    fake_socket = FakeSocket(b"+OK\r\n+OK\r\n:1\r\n")
    monkeypatch.setattr(
        "app.core.redis_client.socket.create_connection",
        lambda *_args, **_kwargs: fake_socket,
    )
    client = RedisClient("localhost", 6379, database=2, password="secret")

    assert client.execute_command("SET", "key", b"value") == 1
    assert fake_socket.sent == [
        b"*2\r\n$4\r\nAUTH\r\n$6\r\nsecret\r\n",
        b"*2\r\n$6\r\nSELECT\r\n$1\r\n2\r\n",
        b"*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n",
    ]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"+PONG\r\n", "PONG"),
        (b":12\r\n", 12),
        (b"$3\r\nabc\r\n", b"abc"),
        (b"$-1\r\n", None),
        (b"*2\r\n$1\r\na\r\n:2\r\n", [b"a", 2]),
    ],
)
def test_resp2_reply_types_are_decoded(response, expected):
    assert RedisClient._read_response(BytesIO(response)) == expected


def test_resp_error_reply_becomes_a_redis_command_error():
    with pytest.raises(RedisCommandError, match="WRONGTYPE"):
        RedisClient._read_response(BytesIO(b"-WRONGTYPE bad value\r\n"))

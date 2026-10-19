"""Tests for the small RESP2 client used by the core Redis input store."""

from io import BytesIO
from unittest.mock import Mock

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


def test_redis_url_supports_password_only_and_default_port():
    client = RedisClient.from_url("redis://:p%40ss@redis.internal")

    assert (client.host, client.port, client.database) == ("redis.internal", 6379, 0)
    assert client.username is None
    assert client.password == "p@ss"


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


@pytest.mark.parametrize(
    "response",
    [b"", b"+incomplete", b"$4\r\nabc\r\n", b"?unknown\r\n"],
)
def test_malformed_resp_replies_raise_oserror(response):
    with pytest.raises(OSError):
        RedisClient._read_response(BytesIO(response))


def test_redis_url_rejects_non_numeric_database_and_invalid_port():
    with pytest.raises(ValueError, match="database"):
        RedisClient.from_url("redis://redis.internal/not-a-number")
    with pytest.raises(ValueError):
        RedisClient.from_url("redis://redis.internal:invalid")


def test_redis_client_command_helpers_delegate_and_convert_results(monkeypatch):
    client = RedisClient("redis", 6379)
    execute = Mock(side_effect=[2, 1, 1, [b"a", b"1"], b"value", None, 3])
    monkeypatch.setattr(client, "execute_command", execute)

    assert client.hset("hash", {"a": b"1"}) == 2
    assert client.expire("hash", 30) is True
    assert client.eval("return 1", 0) == 1
    assert client.hgetall("hash") == {b"a": b"1"}
    assert client.get("key") == b"value"
    assert client.get("missing") is None
    assert client.delete("one", "two") == 3
    client.close()
    assert execute.call_count == 7


def test_resp_parser_supports_nil_and_nested_arrays():
    response = BytesIO(b"*-1\r\n")
    assert RedisClient._read_response(response) is None
    nested = BytesIO(b"*2\r\n*2\r\n:1\r\n:2\r\n$-1\r\n")
    assert RedisClient._read_response(nested) == [[1, 2], None]


def test_execute_command_without_auth_or_database(monkeypatch):
    fake_socket = FakeSocket(b"+OK\r\n")
    monkeypatch.setattr(
        "app.core.redis_client.socket.create_connection",
        lambda *_args, **_kwargs: fake_socket,
    )
    client = RedisClient("localhost", 6379)

    assert client.execute_command("PING") == "OK"
    assert fake_socket.sent == [b"*1\r\n$4\r\nPING\r\n"]

"""Minimal RESP2 Redis client used only by the rate-limiter service."""

from __future__ import annotations

import socket
from urllib.parse import unquote, urlsplit


class RedisCommandError(RuntimeError):
    """Raised when Redis rejects a command."""


class RedisClient:
    """Issue only the Redis commands required for permit reservation.

    Args:
        host: Redis DNS name or IP address.
        port: Redis TCP port.
        database: Redis logical database number.
        username: Optional Redis ACL username.
        password: Optional Redis password.
        socket_timeout: Connection and response timeout in seconds.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: int,
        username: str | None,
        password: str | None,
        socket_timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.socket_timeout = socket_timeout

    @classmethod
    def from_url(cls, url: str, socket_timeout: float = 5.0) -> "RedisClient":
        """Create a client from a ``redis://`` URL."""
        parsed = urlsplit(url)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("Redis URL must use redis:// and include a host")
        try:
            database = int(parsed.path.removeprefix("/") or "0")
        except ValueError as error:
            raise ValueError("Redis database must be a nonnegative integer") from error
        if database < 0:
            raise ValueError("Redis database must be a nonnegative integer")
        return cls(
            parsed.hostname,
            parsed.port or 6379,
            database,
            unquote(parsed.username) if parsed.username else None,
            unquote(parsed.password) if parsed.password else None,
            socket_timeout,
        )

    def set_if_absent(self, key: str, ttl_ms: int) -> bool:
        """Atomically acquire a key if absent and expire it after ``ttl_ms``."""
        return self.execute("SET", key, "1", "NX", "PX", ttl_ms) == "OK"

    def ttl_milliseconds(self, key: str) -> int:
        """Read the remaining permit delay for a bucket key."""
        return int(self.execute("PTTL", key))

    def execute(self, *parts: str | int):
        """Send one Redis command and parse its RESP2 response."""
        with socket.create_connection(
            (self.host, self.port), timeout=self.socket_timeout
        ) as connection:
            connection.settimeout(self.socket_timeout)
            reader = connection.makefile("rb")
            if self.password is not None:
                auth = (
                    ("AUTH", self.username, self.password)
                    if self.username is not None
                    else ("AUTH", self.password)
                )
                self._send(connection, auth)
                self._read(reader)
            if self.database:
                self._send(connection, ("SELECT", self.database))
                self._read(reader)
            self._send(connection, parts)
            return self._read(reader)

    @staticmethod
    def _send(connection: socket.socket, parts: tuple[str | int, ...]) -> None:
        encoded = [str(part).encode("utf-8") for part in parts]
        chunks = [f"*{len(encoded)}\r\n".encode()]
        for item in encoded:
            chunks.extend((f"${len(item)}\r\n".encode(), item, b"\r\n"))
        connection.sendall(b"".join(chunks))

    @classmethod
    def _read(cls, reader):
        marker = reader.read(1)
        line = reader.readline()
        if not marker or not line.endswith(b"\r\n"):
            raise OSError("Redis returned an incomplete response")
        value = line[:-2]
        if marker == b"+":
            return value.decode("utf-8")
        if marker == b"-":
            raise RedisCommandError(value.decode("utf-8", errors="replace"))
        if marker == b":":
            return int(value)
        if marker == b"$":
            size = int(value)
            if size < 0:
                return None
            data = reader.read(size + 2)
            if len(data) != size + 2 or not data.endswith(b"\r\n"):
                raise OSError("Redis returned an incomplete bulk response")
            return data[:-2].decode("utf-8")
        raise OSError(f"Unsupported Redis RESP marker: {marker!r}")

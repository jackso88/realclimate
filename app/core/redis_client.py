"""Minimal binary-safe RESP client for the core's Redis input store."""

from __future__ import annotations

import socket
from collections.abc import Callable, Sequence
from urllib.parse import unquote, urlsplit


class RedisCommandError(RuntimeError):
    """Raised when Redis returns an error response to a command."""


class RedisClient:
    """Small synchronous Redis client supporting the commands core requires.

    A fresh TCP connection is used for each command, keeping connection state
    isolated and making service recovery straightforward. Redis traffic stays
    on the private Docker network and supports the ``redis://`` URL scheme.

    Args:
        host: Redis DNS name or IP address.
        port: Redis TCP port.
        database: Redis logical database number.
        username: Optional ACL username.
        password: Optional Redis password.
        socket_timeout: Timeout for connection and command response in seconds.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: int = 0,
        username: str | None = None,
        password: str | None = None,
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
        """Create a client from a Redis URL.

        Args:
            url: ``redis://[username:password@]host:port/database`` URL.
            socket_timeout: Maximum duration of a connection or command.

        Returns:
            A client configured for the URL's host, credentials, and database.

        Raises:
            ValueError: If the URL scheme or components are invalid.
        """
        parsed = urlsplit(url)
        if parsed.scheme != "redis" or not parsed.hostname:
            raise ValueError("Redis URL must use redis:// and include a host")
        database_text = parsed.path.removeprefix("/") or "0"
        try:
            database = int(database_text)
        except ValueError as error:
            raise ValueError(
                "Redis URL database must be a nonnegative integer"
            ) from error
        if database < 0:
            raise ValueError("Redis URL database must be a nonnegative integer")
        return cls(
            host=parsed.hostname,
            port=parsed.port or 6379,
            database=database,
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
            socket_timeout=socket_timeout,
        )

    def hset(self, key: str, mapping: dict[str, bytes]) -> int:
        """Set multiple binary-safe hash fields."""
        command: list[str | bytes | int] = ["HSET", key]
        for field, value in mapping.items():
            command.extend((field, value))
        return int(self.execute_command(*command))

    def expire(self, key: str, seconds: int) -> bool:
        """Set the key's expiration in seconds."""
        return bool(self.execute_command("EXPIRE", key, seconds))

    def hgetall(self, key: str) -> dict[bytes, bytes]:
        """Return a Redis hash as a dictionary of raw byte fields and values."""
        response = self.execute_command("HGETALL", key)
        return dict(zip(response[::2], response[1::2]))

    def get(self, key: str) -> bytes | None:
        """Read a binary-safe string value, or return ``None`` if absent."""
        return self.execute_command("GET", key)

    def delete(self, *keys: str) -> int:
        """Delete one or more Redis keys."""
        return int(self.execute_command("DEL", *keys))

    def transaction(
        self,
        *,
        watch_keys: Sequence[str],
        read_commands: Sequence[Sequence[str | bytes | int]],
        condition: Callable[[list], bool],
        write_commands: Sequence[Sequence[str | bytes | int]],
    ) -> bool:
        """Run conditional Redis commands atomically using WATCH/MULTI/EXEC.

        Args:
            watch_keys: Keys whose changes should abort the transaction.
            read_commands: Read-only Redis commands evaluated after WATCH.
            condition: Predicate over the read replies deciding whether to
                execute the writes.
            write_commands: Commands queued and executed atomically when the
                condition is true.

        Returns:
            ``True`` if EXEC committed, or ``False`` if the predicate failed
            or a watched key changed before EXEC.
        """
        with socket.create_connection(
            (self.host, self.port), timeout=self.socket_timeout
        ) as connection:
            connection.settimeout(self.socket_timeout)
            reader = connection.makefile("rb")
            self._initialize_connection(connection, reader)
            self._send_command(connection, ("WATCH", *watch_keys))
            self._read_response(reader)
            replies = []
            for command in read_commands:
                self._send_command(connection, command)
                response = self._read_response(reader)
                if command[0] == "HGETALL":
                    response = dict(zip(response[::2], response[1::2]))
                replies.append(response)
            if not condition(replies):
                self._send_command(connection, ("UNWATCH",))
                self._read_response(reader)
                return False
            self._send_command(connection, ("MULTI",))
            self._read_response(reader)
            for command in write_commands:
                self._send_command(connection, command)
                self._read_response(reader)
            self._send_command(connection, ("EXEC",))
            return self._read_response(reader) is not None

    def close(self) -> None:
        """Close hook matching common Redis client interfaces.

        Connections are closed after each command, so there is no persistent
        socket to close.
        """

    def execute_command(self, *parts: str | bytes | int):
        """Send one command and decode its RESP2 reply.

        Args:
            parts: Redis command name followed by command arguments.

        Returns:
            Redis simple strings and integers as Python values, bulk strings as
            bytes, arrays as lists, and nil replies as ``None``.

        Raises:
            RedisCommandError: If Redis replies with an error.
            OSError: If the Redis server cannot be reached or the connection
                fails while reading or writing.
        """
        with socket.create_connection(
            (self.host, self.port), timeout=self.socket_timeout
        ) as connection:
            connection.settimeout(self.socket_timeout)
            reader = connection.makefile("rb")
            self._initialize_connection(connection, reader)
            self._send_command(connection, parts)
            return self._read_response(reader)

    def _initialize_connection(self, connection, reader) -> None:
        if self.password is not None:
            if self.username is None:
                self._send_command(connection, ("AUTH", self.password))
            else:
                self._send_command(connection, ("AUTH", self.username, self.password))
            self._read_response(reader)
        if self.database:
            self._send_command(connection, ("SELECT", self.database))
            self._read_response(reader)

    @staticmethod
    def _send_command(connection: socket.socket, parts) -> None:
        encoded = [
            part if isinstance(part, bytes) else str(part).encode() for part in parts
        ]
        message = [f"*{len(encoded)}\r\n".encode()]
        for part in encoded:
            message.extend((f"${len(part)}\r\n".encode(), part, b"\r\n"))
        connection.sendall(b"".join(message))

    @classmethod
    def _read_response(cls, reader):
        marker = reader.read(1)
        line = reader.readline()
        if not marker or not line.endswith(b"\r\n"):
            raise OSError("Redis returned an incomplete RESP response")
        value = line[:-2]
        if marker == b"+":
            return value.decode("utf-8")
        if marker == b"-":
            raise RedisCommandError(value.decode("utf-8", errors="replace"))
        if marker == b":":
            return int(value)
        if marker == b"$":
            length = int(value)
            if length < 0:
                return None
            bulk = reader.read(length + 2)
            if len(bulk) != length + 2 or not bulk.endswith(b"\r\n"):
                raise OSError("Redis returned an incomplete bulk response")
            return bulk[:-2]
        if marker == b"*":
            length = int(value)
            if length < 0:
                return None
            return [cls._read_response(reader) for _ in range(length)]
        raise OSError(f"Redis returned an unknown RESP type: {marker!r}")

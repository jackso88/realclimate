"""Domain exceptions raised by rate limitter."""


class RedisCommandError(RuntimeError):
    """Raised when Redis rejects a command."""

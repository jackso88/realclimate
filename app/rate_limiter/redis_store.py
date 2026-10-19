"""Atomic permit reservation using Redis SET NX with an expiration window."""


class RedisPermitStore:
    """Reserve one permit per configured interval in a shared Redis database.

    Args:
        client: Redis-compatible client exposing ``set_if_absent`` and
            ``ttl_milliseconds`` operations.
        key_prefix: Namespace for the limiter's Redis keys.
    """

    def __init__(self, client, key_prefix: str = "rate-limit") -> None:
        self.client = client
        self.key_prefix = key_prefix.rstrip(":")

    def acquire(self, bucket: str, interval_ms: int) -> tuple[bool, int]:
        """Attempt to reserve a permit without allowing a burst.

        Args:
            bucket: Shared quota name, such as ``cms:account``.
            interval_ms: Minimum time between permits, in milliseconds.

        Returns:
            A tuple of ``(granted, retry_after_ms)``. A granted permit has a
            zero delay; a denied permit reports the remaining key TTL.
        """
        if interval_ms < 1:
            raise ValueError("interval_ms must be positive")
        key = f"{self.key_prefix}:{bucket}"
        if self.client.set_if_absent(key, interval_ms):
            return True, 0
        return False, max(0, self.client.ttl_milliseconds(key))

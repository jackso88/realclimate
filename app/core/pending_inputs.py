"""Redis-backed, correlation-keyed storage for incomplete core input pairs."""

from __future__ import annotations

_CLAIM_PAIR_SCRIPT = """
if redis.call('EXISTS', KEYS[3]) == 0
   and redis.call('HEXISTS', KEYS[1], 'reference_csv') == 1
   and redis.call('HEXISTS', KEYS[1], 'current_csv') == 1 then
    return redis.call('SET', KEYS[2], ARGV[1], 'NX', 'EX', ARGV[2]) and 1 or 0
end
return 0
"""

_RELEASE_CLAIM_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_COMPLETE_PAIR_SCRIPT = """
if redis.call('GET', KEYS[2]) == ARGV[1] then
    redis.call('DEL', KEYS[1], KEYS[2])
    redis.call('SET', KEYS[3], '1', 'EX', ARGV[2])
    return 1
end
return 0
"""


class RedisPendingInputsStore:
    """Store reference/current CSV parts until both are ready for core.

    Args:
        client: A Redis-compatible client using binary-safe responses.
        ttl_seconds: Expiration for incomplete input pairs.
        claim_ttl_seconds: Lease duration that prevents concurrent processing
            of the same correlation ID. The lease permits recovery after a
            worker exits unexpectedly.
        key_prefix: Namespace used for all Redis keys owned by this store.
    """

    def __init__(
        self,
        client,
        ttl_seconds: int = 86_400,
        claim_ttl_seconds: int = 7_200,
        key_prefix: str = "core:pending",
    ) -> None:
        if ttl_seconds < 1 or claim_ttl_seconds < 1:
            raise ValueError("Redis pending-input TTL values must be positive")
        self.client = client
        self.ttl_seconds = ttl_seconds
        self.claim_ttl_seconds = claim_ttl_seconds
        self.key_prefix = key_prefix.rstrip(":")

    def save_reference(
        self, correlation_id: str, content: bytes, sha256: str, claim_token: str
    ) -> bool:
        """Persist reference bytes and digest, then atomically claim a pair.

        Args:
            correlation_id: Pipeline identifier shared by both downloader events.
            content: Raw reference CSV bytes.
            sha256: SHA-256 digest of the downloaded reference content.
            claim_token: Unique token for this worker's processing lease.

        Returns:
            ``True`` if both inputs are present and this call acquired the
            processing lease; otherwise ``False``.
        """
        self._save_fields(
            correlation_id,
            {"reference_csv": content, "reference_sha256": sha256.encode("ascii")},
        )
        return self._claim_if_ready(correlation_id, claim_token)

    def save_current(
        self, correlation_id: str, content: bytes, claim_token: str
    ) -> bool:
        """Persist current CSV bytes, then atomically claim a complete pair.

        Args:
            correlation_id: Pipeline identifier shared by both downloader events.
            content: Raw current catalogue CSV bytes.
            claim_token: Unique token for this worker's processing lease.

        Returns:
            ``True`` if both inputs are present and this call acquired the
            processing lease; otherwise ``False``.
        """
        self._save_fields(correlation_id, {"current_csv": content})
        return self._claim_if_ready(correlation_id, claim_token)

    def get_pair(self, correlation_id: str) -> tuple[bytes, bytes, str]:
        """Read a complete pair after this worker has acquired its lease.

        Args:
            correlation_id: Pipeline identifier used as the Redis key suffix.

        Returns:
            Reference bytes, current bytes, and reference SHA-256 digest.

        Raises:
            KeyError: If any required part expired or is missing.
        """
        values = self.client.hgetall(self._input_key(correlation_id))
        try:
            return (
                values[b"reference_csv"],
                values[b"current_csv"],
                values[b"reference_sha256"].decode("ascii"),
            )
        except KeyError as error:
            raise KeyError(
                f"Incomplete Redis input pair for correlation_id={correlation_id}"
            ) from error

    def is_completed(self, correlation_id: str) -> bool:
        """Check whether this pipeline ID was already processed successfully.

        Args:
            correlation_id: Pipeline identifier to check.

        Returns:
            ``True`` while the completion marker remains within its TTL.
        """
        return self.client.get(self._completed_key(correlation_id)) is not None

    def complete(self, correlation_id: str, token: str) -> bool:
        """Delete the pair and mark it completed after successful output.

        Args:
            correlation_id: Pipeline identifier to remove from Redis.
            token: Claim token that must still own the processing lease.

        Returns:
            ``True`` when this worker removed the pair and wrote a completion
            marker, or ``False`` if its lease expired or changed owners.
        """
        return bool(
            self.client.eval(
                _COMPLETE_PAIR_SCRIPT,
                3,
                self._input_key(correlation_id),
                self._claim_key(correlation_id),
                self._completed_key(correlation_id),
                token,
                self.ttl_seconds,
            )
        )

    def release(self, correlation_id: str, token: str) -> None:
        """Release this worker's lease while retaining inputs for retry.

        Args:
            correlation_id: Pipeline identifier whose lease should be released.
            token: Claim token returned by :meth:`new_claim_token`.
        """
        self.client.eval(
            _RELEASE_CLAIM_SCRIPT, 1, self._claim_key(correlation_id), token
        )

    def _save_fields(self, correlation_id: str, fields: dict[str, bytes]) -> None:
        if not correlation_id:
            raise ValueError("correlation_id is required for Redis input storage")
        key = self._input_key(correlation_id)
        self.client.hset(key, mapping=fields)
        self.client.expire(key, self.ttl_seconds)

    def _claim_if_ready(self, correlation_id: str, token: str) -> bool:
        result = self.client.eval(
            _CLAIM_PAIR_SCRIPT,
            3,
            self._input_key(correlation_id),
            self._claim_key(correlation_id),
            self._completed_key(correlation_id),
            token,
            self.claim_ttl_seconds,
        )
        return bool(result)

    def _input_key(self, correlation_id: str) -> str:
        return f"{self.key_prefix}:{correlation_id}"

    def _claim_key(self, correlation_id: str) -> str:
        return f"{self.key_prefix}:claim:{correlation_id}"

    def _completed_key(self, correlation_id: str) -> str:
        return f"{self.key_prefix}:completed:{correlation_id}"

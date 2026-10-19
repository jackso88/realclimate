"""Tests for correlation-based Redis storage of core downloader inputs."""

import pytest

from app.core.pending_inputs import (
    _CLAIM_PAIR_SCRIPT,
    _COMPLETE_PAIR_SCRIPT,
    _RELEASE_CLAIM_SCRIPT,
    RedisPendingInputsStore,
)


class FakeRedis:
    """Small binary-safe Redis fake implementing the store's used commands."""

    def __init__(self):
        self.hashes = {}
        self.values = {}
        self.expiries = {}
        self.deleted = []

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(
            {field.encode(): value for field, value in mapping.items()}
        )

    def expire(self, key, seconds):
        self.expiries[key] = seconds

    def hgetall(self, key):
        return self.hashes.get(key, {}).copy()

    def eval(self, script, key_count, *args):
        if script == _CLAIM_PAIR_SCRIPT:
            input_key, claim_key, completed_key, token, ttl = args
            fields = self.hashes.get(input_key, {})
            if (
                completed_key in self.values
                or b"reference_csv" not in fields
                or b"current_csv" not in fields
            ):
                return 0
            if claim_key in self.values:
                return 0
            self.values[claim_key] = token.encode()
            self.expiries[claim_key] = int(ttl)
            return 1
        if script == _RELEASE_CLAIM_SCRIPT:
            claim_key, token = args
            if self.values.get(claim_key) == token.encode():
                del self.values[claim_key]
                return 1
            return 0
        if script == _COMPLETE_PAIR_SCRIPT:
            input_key, claim_key, completed_key, token, ttl = args
            if self.values.get(claim_key) == token.encode():
                self.hashes.pop(input_key, None)
                del self.values[claim_key]
                self.values[completed_key] = b"1"
                self.expiries[completed_key] = int(ttl)
                return 1
            return 0
        raise AssertionError("Unexpected Redis script")

    def delete(self, *keys):
        self.deleted.extend(keys)
        for key in keys:
            self.hashes.pop(key, None)
            self.values.pop(key, None)

    def get(self, key):
        return self.values.get(key)


def test_pair_is_claimed_only_after_both_parts_arrive():
    redis = FakeRedis()
    store = RedisPendingInputsStore(redis, key_prefix="test:inputs")

    assert store.save_reference("corr-1", b"ref", "digest", "token-1") is False
    assert store.save_current("corr-1", b"current", "token-2") is True
    assert store.save_current("corr-1", b"current", "token-3") is False
    assert store.get_pair("corr-1") == (b"ref", b"current", "digest")


def test_parts_are_namespaced_by_correlation_and_expire():
    redis = FakeRedis()
    store = RedisPendingInputsStore(redis, ttl_seconds=123, key_prefix="test:inputs:")

    store.save_reference("corr-a", b"a", "hash-a", "token-a")
    store.save_reference("corr-b", b"b", "hash-b", "token-b")

    assert redis.expiries["test:inputs:corr-a"] == 123
    assert redis.expiries["test:inputs:corr-b"] == 123
    assert redis.hashes["test:inputs:corr-a"][b"reference_csv"] == b"a"
    assert redis.hashes["test:inputs:corr-b"][b"reference_csv"] == b"b"


def test_release_requires_the_current_workers_claim_token():
    redis = FakeRedis()
    store = RedisPendingInputsStore(redis, key_prefix="test:inputs")
    store.save_reference("corr-1", b"ref", "digest", "token-1")
    store.save_current("corr-1", b"current", "token-2")

    store.release("corr-1", "wrong-token")
    assert redis.values["test:inputs:claim:corr-1"] == b"token-2"

    store.release("corr-1", "token-2")
    assert "test:inputs:claim:corr-1" not in redis.values
    assert "test:inputs:corr-1" in redis.hashes


def test_complete_removes_pair_and_claim():
    redis = FakeRedis()
    store = RedisPendingInputsStore(redis, key_prefix="test:inputs")
    store.save_reference("corr-1", b"ref", "digest", "token-1")
    store.save_current("corr-1", b"current", "token-2")

    assert store.complete("corr-1", "token-2") is True

    assert "test:inputs:corr-1" not in redis.hashes
    assert "test:inputs:claim:corr-1" not in redis.values
    assert store.is_completed("corr-1") is True
    assert redis.expiries["test:inputs:completed:corr-1"] == 86_400


def test_stale_worker_cannot_delete_a_pair_owned_by_another_claim():
    redis = FakeRedis()
    store = RedisPendingInputsStore(redis, key_prefix="test:inputs")
    store.save_reference("corr-1", b"ref", "digest", "token-1")
    store.save_current("corr-1", b"current", "token-2")

    assert store.complete("corr-1", "stale-token") is False
    assert "test:inputs:corr-1" in redis.hashes
    assert redis.values["test:inputs:claim:corr-1"] == b"token-2"


@pytest.mark.parametrize("ttl", [0, -1])
def test_nonpositive_expiry_is_rejected(ttl):
    with pytest.raises(ValueError, match="must be positive"):
        RedisPendingInputsStore(FakeRedis(), ttl_seconds=ttl)

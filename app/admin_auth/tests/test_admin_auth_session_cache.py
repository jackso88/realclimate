"""Tests for the admin authentication snapshot TTL cache."""

import pytest

from app.admin_auth.models import AdminSettings, SessionSnapshot
from app.admin_auth.session_cache import SessionSnapshotCache


def make_settings(ttl=10, username="user"):
    return AdminSettings(
        base_url="https://admin.invalid",
        cms_url="https://admin.invalid/cms",
        username=username,
        password="secret",
        access="token",
        ver_id=123,
        design_id=456,
        session_cache_ttl_seconds=ttl,
    )


def test_cache_reuses_snapshot_until_ttl_expiration():
    now = [100.0]
    cache = SessionSnapshotCache(clock=lambda: now[0])
    settings = make_settings()
    factory = lambda _settings: SessionSnapshot(
        cookies=[], headers={"X-Session": "one"}
    )

    first = cache.get(settings, factory)
    second = cache.get(settings, lambda _settings: pytest.fail("unexpected login"))
    now[0] = 110.0
    third = cache.get(settings, factory)

    assert second is first
    assert third is not first


def test_cache_refreshes_when_auth_settings_change():
    cache = SessionSnapshotCache(clock=lambda: 5.0)
    first_settings = make_settings(username="first")
    second_settings = make_settings(username="second")
    first_snapshot = SessionSnapshot(cookies=[], headers={"X-Session": "first"})
    second_snapshot = SessionSnapshot(cookies=[], headers={"X-Session": "second"})

    assert cache.get(first_settings, lambda _: first_snapshot) is first_snapshot
    assert cache.get(second_settings, lambda _: second_snapshot) is second_snapshot


def test_failed_authentication_is_not_cached_and_can_be_retried():
    cache = SessionSnapshotCache(clock=lambda: 1.0)
    settings = make_settings()
    expected = SessionSnapshot(cookies=[], headers={"X-Session": "valid"})
    calls = 0

    def factory(_settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("login failed")
        return expected

    with pytest.raises(RuntimeError, match="login failed"):
        cache.get(settings, factory)

    assert cache.get(settings, factory) is expected
    assert calls == 2


def test_clear_discards_cached_snapshot():
    cache = SessionSnapshotCache(clock=lambda: 1.0)
    settings = make_settings()
    first = SessionSnapshot(cookies=[], headers={"X-Session": "first"})
    second = SessionSnapshot(cookies=[], headers={"X-Session": "second"})
    cache.get(settings, lambda _: first)
    cache.clear()

    assert cache.get(settings, lambda _: second) is second

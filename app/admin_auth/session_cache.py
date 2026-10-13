"""Process-local TTL cache for authenticated CMS session snapshots."""

import threading
import time
from collections.abc import Callable

from app.admin_auth.models import AdminSettings, SessionSnapshot

SnapshotFactory = Callable[[AdminSettings], SessionSnapshot]


class SessionSnapshotCache:
    """Reuse one authenticated session snapshot until its TTL expires.

    The cache stores the serializable snapshot rather than a live
    :class:`requests.Session`. Each caller can restore its own local session
    from the snapshot without sharing mutable HTTP client state.

    Args:
        clock: Monotonic clock used to calculate expiration, injectable in tests.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._settings: AdminSettings | None = None
        self._snapshot: SessionSnapshot | None = None
        self._expires_at = 0.0

    def get(
        self,
        settings: AdminSettings,
        factory: SnapshotFactory,
    ) -> SessionSnapshot:
        """Return a cached snapshot or create and cache a new one.

        Args:
            settings: Authentication settings used to create the snapshot.
            factory: Function that performs the CMS authentication flow.

        Returns:
            A session snapshot valid for the configured TTL.

        Raises:
            Exception: Propagates authentication errors and leaves the cache
                empty so a later request can retry.
        """
        with self._lock:
            now = self._clock()
            if (
                self._snapshot is not None
                and self._settings == settings
                and now < self._expires_at
            ):
                return self._snapshot

            self._clear_unlocked()
            snapshot = factory(settings)
            self._settings = settings
            self._snapshot = snapshot
            self._expires_at = self._clock() + settings.session_cache_ttl_seconds
            return snapshot

    def clear(self) -> None:
        """Discard any cached snapshot immediately."""
        with self._lock:
            self._clear_unlocked()

    def _clear_unlocked(self) -> None:
        """Reset state while the caller holds the cache lock."""
        self._settings = None
        self._snapshot = None
        self._expires_at = 0.0

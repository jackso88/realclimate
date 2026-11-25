"""PostgreSQL-backed persistent state for the core worker."""

from __future__ import annotations

import logging
from collections.abc import Collection, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

LEGACY_IMPORT_FLAG = "absent_articles.legacy_import_done"

_DELETE_MISSING = "DELETE FROM absent_articles WHERE article <> ALL(%s::text[])"
_INSERT_ALL = (
    "INSERT INTO absent_articles (article) "
    "SELECT unnest(%s::text[]) ON CONFLICT (article) DO NOTHING"
)
_SELECT_ALL = "SELECT article FROM absent_articles"
_SELECT_FLAG = "SELECT 1 FROM app_state WHERE key = %s"
_INSERT_FLAG = (
    "INSERT INTO app_state (key, value) VALUES (%s, %s) "
    "ON CONFLICT (key) DO NOTHING"
)


class StateStoreError(Exception):
    """Raised when PostgreSQL is unreachable or rejects a state command."""


def _is_database_error(error: Exception) -> bool:
    """Tell whether an exception is a connectivity or database failure.

    Args:
        error: Exception raised while talking to PostgreSQL.

    Returns:
        ``True`` for operating-system level and psycopg errors, which are
        worth retrying; ``False`` for programming errors.
    """
    if isinstance(error, OSError):
        return True
    try:
        import psycopg
    except ImportError:
        return False
    return isinstance(error, psycopg.Error)


class AbsentArticlesStore:
    """Persist the articles hidden because the supplier catalogue dropped them.

    The set used to live in a compacted Kafka topic. Every operation opens a
    short-lived connection and runs in one transaction, which is plenty for a
    handful of catalogue runs per day.

    Args:
        database_url: PostgreSQL connection URL.
        connect: Optional connection factory, mainly for tests. It must return
            a context manager that yields an object with ``execute``.
    """

    def __init__(self, database_url: str, connect=None) -> None:
        self.database_url = database_url
        self._connect = connect or self._connect_psycopg

    def _connect_psycopg(self):
        """Open a psycopg connection to the configured database."""
        import psycopg

        return psycopg.connect(self.database_url, connect_timeout=10)

    @contextmanager
    def _transaction(self) -> Iterator:
        """Yield a connection that commits on success and rolls back on error.

        Raises:
            StateStoreError: If PostgreSQL is unreachable or rejects a command.
        """
        try:
            with self._connect() as connection:
                yield connection
        except Exception as error:
            if _is_database_error(error):
                raise StateStoreError(
                    f"PostgreSQL state store failed: {error}"
                ) from error
            raise

    @staticmethod
    def _replace(connection, articles: Collection[str]) -> None:
        """Make the stored set equal to ``articles`` inside an open transaction."""
        values = sorted(set(articles))
        connection.execute(_DELETE_MISSING, (values,))
        if values:
            connection.execute(_INSERT_ALL, (values,))

    def load(self) -> set[str]:
        """Read the tracked absent articles.

        Returns:
            The set of article codes; empty when nothing is tracked.

        Raises:
            StateStoreError: If PostgreSQL is unreachable or rejects the query.
        """
        with self._transaction() as connection:
            rows = connection.execute(_SELECT_ALL).fetchall()
        return {str(row[0]) for row in rows}

    def replace(self, articles: Collection[str]) -> None:
        """Atomically replace the tracked set, keeping the original hide time.

        Args:
            articles: The complete set that should be tracked after this run.

        Raises:
            StateStoreError: If PostgreSQL is unreachable or rejects a command.
        """
        with self._transaction() as connection:
            self._replace(connection, articles)

    def legacy_import_done(self) -> bool:
        """Tell whether the old Kafka state has already been imported.

        Returns:
            ``True`` once :meth:`import_legacy` has completed.

        Raises:
            StateStoreError: If PostgreSQL is unreachable or rejects the query.
        """
        with self._transaction() as connection:
            row = connection.execute(_SELECT_FLAG, (LEGACY_IMPORT_FLAG,)).fetchone()
        return row is not None

    def import_legacy(self, articles: Collection[str]) -> None:
        """Store the state read from the old Kafka topic and mark it imported.

        The articles and the completion flag are written in one transaction, so
        the import either happens fully or not at all.

        Args:
            articles: Articles tracked by the previous Kafka-based state.

        Raises:
            StateStoreError: If PostgreSQL is unreachable or rejects a command.
        """
        with self._transaction() as connection:
            self._replace(connection, articles)
            connection.execute(_INSERT_FLAG, (LEGACY_IMPORT_FLAG, "1"))
        logger.info("Imported %d absent articles from Kafka state", len(set(articles)))

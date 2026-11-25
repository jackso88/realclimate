"""Tests for the PostgreSQL-backed absent-article state store."""

import pytest

from app.core.models import CoreSettings
from app.core.state_store import (
    LEGACY_IMPORT_FLAG,
    AbsentArticlesStore,
    StateStoreError,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self, results=None, error=None):
        self.results = list(results or [])
        self.error = error
        self.executed = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True
        return False

    def execute(self, sql, params=None):
        if self.error is not None:
            raise self.error
        self.executed.append((" ".join(sql.split()), params))
        return FakeCursor(self.results.pop(0) if self.results else [])


def make_store(connection):
    opened = []

    def connect():
        opened.append(connection)
        return connection

    return AbsentArticlesStore("postgresql://unused", connect=connect), opened


def test_load_returns_stored_articles_as_a_set():
    connection = FakeConnection(results=[[("NC-1",), ("NC-2",)]])
    store, _ = make_store(connection)

    assert store.load() == {"NC-1", "NC-2"}
    assert connection.executed[0][0] == "SELECT article FROM absent_articles"
    assert connection.closed


def test_load_of_an_empty_table_is_an_empty_set():
    store, _ = make_store(FakeConnection())

    assert store.load() == set()


def test_replace_deletes_missing_articles_then_inserts_the_set_sorted():
    connection = FakeConnection()
    store, opened = make_store(connection)

    store.replace({"NC-2", "NC-1"})

    delete, insert = connection.executed
    assert delete[0].startswith("DELETE FROM absent_articles WHERE article")
    assert delete[1] == (["NC-1", "NC-2"],)
    assert insert[0].startswith("INSERT INTO absent_articles")
    assert "ON CONFLICT (article) DO NOTHING" in insert[0]
    assert insert[1] == (["NC-1", "NC-2"],)
    assert len(opened) == 1


def test_replace_with_an_empty_set_only_clears_the_table():
    connection = FakeConnection()
    store, _ = make_store(connection)

    store.replace(set())

    assert len(connection.executed) == 1
    assert connection.executed[0][1] == ([],)


@pytest.mark.parametrize("row,expected", [([(1,)], True), ([], False)])
def test_legacy_import_flag_reflects_the_stored_marker(row, expected):
    connection = FakeConnection(results=[row])
    store, _ = make_store(connection)

    assert store.legacy_import_done() is expected
    assert connection.executed[0][1] == (LEGACY_IMPORT_FLAG,)


def test_import_legacy_writes_articles_and_flag_in_one_transaction():
    connection = FakeConnection()
    store, opened = make_store(connection)

    store.import_legacy({"NC-1"})

    assert len(opened) == 1
    assert len(connection.executed) == 3
    flag_sql, flag_params = connection.executed[-1]
    assert flag_sql.startswith("INSERT INTO app_state")
    assert flag_params == (LEGACY_IMPORT_FLAG, "1")


def test_connection_failure_becomes_a_state_store_error():
    def connect():
        raise OSError("connection refused")

    store = AbsentArticlesStore("postgresql://unused", connect=connect)

    with pytest.raises(StateStoreError, match="connection refused"):
        store.load()


def test_command_failure_becomes_a_state_store_error():
    store, _ = make_store(FakeConnection(error=OSError("server closed")))

    with pytest.raises(StateStoreError, match="server closed"):
        store.replace({"NC-1"})


def test_programming_errors_are_not_disguised_as_retryable_failures():
    store, _ = make_store(FakeConnection(error=ValueError("bad query")))

    with pytest.raises(ValueError, match="bad query"):
        store.load()


def test_settings_read_the_database_url_from_the_environment():
    settings = CoreSettings.model_validate({"DATABASE_URL": "postgresql://u:p@db/x"})

    assert settings.database_url == "postgresql://u:p@db/x"
    assert CoreSettings().database_url.startswith("postgresql://")

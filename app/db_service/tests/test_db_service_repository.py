"""Tests for the ORM queries of the database service."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db_service import repository
from app.db_service.tables import AbsentArticle, AppState, Base


def stored(session_factory):
    with session_factory.begin() as session:
        return repository.get_absent_articles(session)


def test_an_empty_database_tracks_nothing(session_factory):
    assert stored(session_factory) == []


def test_replace_inserts_articles_in_alphabetical_order(session_factory):
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-2", "NC-1"])

    assert stored(session_factory) == ["NC-1", "NC-2"]


def test_replace_removes_articles_that_are_no_longer_absent(session_factory):
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-1", "NC-2"])
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-2", "NC-3"])

    assert stored(session_factory) == ["NC-2", "NC-3"]


def test_replace_keeps_the_original_hide_time_of_kept_articles(session_factory):
    long_ago = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-1"])
    with session_factory.begin() as session:
        session.execute(update(AbsentArticle).values(hidden_at=long_ago))
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-1", "NC-2"])

    with session_factory() as session:
        rows = {
            row.article: row.hidden_at for row in session.scalars(select(AbsentArticle))
        }
    assert rows["NC-1"].year == 2020
    assert set(rows) == {"NC-1", "NC-2"}


def test_replace_with_an_empty_collection_clears_the_table(session_factory):
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-1"])
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, [])

    assert stored(session_factory) == []


def test_replace_deletes_large_differences_in_chunks(session_factory, monkeypatch):
    monkeypatch.setattr(repository, "DELETE_CHUNK_SIZE", 10)
    many = [f"NC-{number:04d}" for number in range(95)]
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, many)
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, many[:5])

    assert stored(session_factory) == many[:5]


def test_legacy_import_is_not_done_in_a_fresh_database(session_factory):
    with session_factory.begin() as session:
        assert repository.is_legacy_import_done(session) is False


def test_legacy_import_stores_articles_and_marks_itself_done(session_factory):
    with session_factory.begin() as session:
        assert repository.import_legacy_absent_articles(session, ["NC-1"]) is True

    with session_factory.begin() as session:
        assert repository.is_legacy_import_done(session) is True
    assert stored(session_factory) == ["NC-1"]


def test_a_second_legacy_import_changes_nothing(session_factory):
    with session_factory.begin() as session:
        repository.import_legacy_absent_articles(session, ["NC-1"])
    with session_factory.begin() as session:
        repository.replace_absent_articles(session, ["NC-9"])
    with session_factory.begin() as session:
        applied = repository.import_legacy_absent_articles(session, ["NC-1", "NC-2"])

    assert applied is False
    assert stored(session_factory) == ["NC-9"]


def test_the_database_rejects_an_empty_article_code(session_factory):
    with pytest.raises(IntegrityError):
        with session_factory.begin() as session:
            session.add(AbsentArticle(article=""))


def test_the_legacy_flag_is_stored_in_the_app_state_table(session_factory):
    with session_factory.begin() as session:
        repository.import_legacy_absent_articles(session, [])

    with session_factory() as session:
        flag = session.get(AppState, repository.LEGACY_IMPORT_FLAG)
    assert flag is not None and flag.value == "1"


def test_constraints_follow_the_naming_convention():
    table = Base.metadata.tables["absent_articles"]
    names = {constraint.name for constraint in table.constraints}

    assert "pk_absent_articles" in names
    assert "ck_absent_articles_article_not_empty" in names

"""Database queries of the database service, written with the SQLAlchemy ORM."""

from collections.abc import Iterable, Iterator, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db_service.tables import AbsentArticle, AppState

LEGACY_IMPORT_FLAG = "absent_articles.legacy_import_done"
# Keeps the number of bind parameters of one DELETE well below database limits.
DELETE_CHUNK_SIZE = 1000


def _chunks(values: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    """Split a sequence into consecutive slices of at most ``size`` items."""
    for start in range(0, len(values), size):
        yield values[start : start + size]


def get_absent_articles(session: Session) -> list[str]:
    """Return every tracked absent article.

    Args:
        session: Open database session.

    Returns:
        The article codes in alphabetical order.
    """
    return sorted(session.scalars(select(AbsentArticle.article)))


def replace_absent_articles(session: Session, articles: Iterable[str]) -> None:
    """Make the tracked set equal to ``articles``.

    Rows that are already tracked keep their original ``hidden_at``; only the
    difference is deleted and inserted.

    Args:
        session: Open database session; the caller commits.
        articles: The complete set that should be tracked afterwards.
    """
    target = set(articles)
    current = set(session.scalars(select(AbsentArticle.article)))
    stale = sorted(current - target)
    for chunk in _chunks(stale, DELETE_CHUNK_SIZE):
        session.execute(delete(AbsentArticle).where(AbsentArticle.article.in_(chunk)))
    session.add_all(
        AbsentArticle(article=article) for article in sorted(target - current)
    )


def is_legacy_import_done(session: Session) -> bool:
    """Tell whether the old Kafka state has already been imported.

    Args:
        session: Open database session.

    Returns:
        ``True`` once :func:`import_legacy_absent_articles` has applied.
    """
    return session.get(AppState, LEGACY_IMPORT_FLAG) is not None


def import_legacy_absent_articles(session: Session, articles: Iterable[str]) -> bool:
    """Store the state read from the old Kafka topic, once.

    The import is idempotent: after it has been applied, repeated calls (for
    example a redelivered Kafka request) change nothing, so a stale legacy
    snapshot can never overwrite newer state.

    Args:
        session: Open database session; the caller commits.
        articles: Articles tracked by the previous Kafka-based state.

    Returns:
        ``True`` if the import was applied, ``False`` if it had been done before.
    """
    if is_legacy_import_done(session):
        return False
    replace_absent_articles(session, articles)
    session.add(AppState(key=LEGACY_IMPORT_FLAG, value="1"))
    return True

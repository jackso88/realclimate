"""Engine and session creation for the database service."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def normalize_database_url(url: str) -> str:
    """Select the psycopg 3 driver for plain PostgreSQL URLs.

    Args:
        url: Connection URL such as ``postgresql://user:password@host/db``.

    Returns:
        The URL using the ``postgresql+psycopg`` dialect. URLs that already name
        a driver, or another database, are returned unchanged.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create a session factory bound to a pooled engine.

    Args:
        database_url: SQLAlchemy or plain PostgreSQL connection URL.

    Returns:
        A factory whose ``begin()`` yields a session that commits on success
        and rolls back on error.
    """
    engine = create_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)

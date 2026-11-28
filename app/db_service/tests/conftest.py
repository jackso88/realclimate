"""Shared fixtures for the database service tests.

The tests run the real ORM code against an in-memory SQLite database, so no
PostgreSQL server is needed.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db_service.tables import Base


@pytest.fixture
def session_factory():
    """A session factory over a fresh in-memory database with all tables."""
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()

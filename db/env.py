"""Alembic environment for the realclimate PostgreSQL schema."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.db_service.database import normalize_database_url
from app.db_service.tables import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The models are the single source of truth: `alembic revision --autogenerate`
# compares them with the database and writes the migration.
target_metadata = Base.metadata


def get_database_url() -> str:
    """Read the database URL from ``DATABASE_URL``.

    Returns:
        A SQLAlchemy URL using the psycopg driver for PostgreSQL.

    Raises:
        RuntimeError: If ``DATABASE_URL`` is missing or empty.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL must be set to run migrations")
    return normalize_database_url(url)


def run_migrations_offline() -> None:
    """Emit migration SQL without connecting to the database."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations over a short-lived database connection."""
    engine = create_engine(get_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""SQLAlchemy table definitions owned by the database service.

The schema is described completely here (types, nullability, defaults,
constraints, comments and a naming convention) so that Alembic can generate
every migration automatically. Migrations are never written by hand.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, MetaData, Text, column, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Explicit names keep generated constraint and index names stable across
# databases, so autogenerate does not report spurious differences.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by every table of the database service."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AbsentArticle(Base):
    """An article hidden because the supplier catalogue no longer lists it."""

    __tablename__ = "absent_articles"
    __table_args__ = (
        CheckConstraint(
            func.length(column("article")) > 0,
            name="article_not_empty",
        ),
        {"comment": "Articles hidden because the supplier no longer lists them"},
    )

    article: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        comment="Article code as it appears in the CMS",
    )
    hidden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="When the article was first hidden",
    )


class AppState(Base):
    """A named service flag or marker, for example a completed one-off import."""

    __tablename__ = "app_state"
    __table_args__ = ({"comment": "Small named markers kept by the services"},)

    key: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        comment="Marker name",
    )
    value: Mapped[str] = mapped_column(Text, comment="Marker value")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="When the marker last changed",
    )

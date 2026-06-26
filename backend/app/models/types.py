"""Cross-cutting type helpers for portable Postgres/SQLite columns.

Lesson from v1: Postgres-only ARRAY blocked integration tests on SQLite. We use
JSON columns instead — JSONB on Postgres, JSON on SQLite. SQLAlchemy's
``JSON`` type handles this transparently.
"""
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CHAR, DateTime
from sqlalchemy.types import JSON, TypeDecorator


class PortableUUID(TypeDecorator):
    """Portable UUID column.

    Postgres: native UUID.
    SQLite: stores as 36-char CHAR (text).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID

            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, UUID):
            value = UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        return UUID(str(value))


def uuid_pk_column() -> Any:
    """Returns a portable UUID primary-key column expression."""
    from sqlalchemy import Column

    return Column(
        PortableUUID(),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )


def created_at_column() -> Any:
    from sqlalchemy import Column

    return Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
        server_default=None,
    )


def updated_at_column() -> Any:
    from sqlalchemy import Column

    return Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        server_default=None,
    )


def portable_json_column() -> Any:
    """JSONB on Postgres, JSON on SQLite. Used for list/dict columns that we
    don't want to be Postgres-only."""
    from sqlalchemy import Column

    return Column(JSON, nullable=False, default=list)
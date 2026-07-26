"""message thread (T8e-booking-agent) — additive on top of 0002_messages

Revision ID: 0006_messages_attachments
Revises: 0005_user_onboarding_fields
Create Date: 2026-07-24

Adds 2 columns to ``messages`` (which was created in 0002_messages) and
creates the ``message_attachments`` table for file uploads:

- ``is_summary`` Boolean NOT NULL default False — marks the message as
  the auto-generated booking summary (the card the user reads for
  dates, passport, visa status).
- ``booking_id`` UUID NULL FK -> bookings_log.id — lets us join thread
  messages back to the booking state machine for the agent dashboard.

``message_attachments`` columns:
  - id            UUID pk
  - message_id    UUID FK -> messages.id (CASCADE)
  - filename      String(255) — sanitised, no path traversal
  - mime_type     String(64)  — allowlisted (image/png|jpeg|webp,
                                application/pdf, text/plain)
  - size_bytes    Integer     — bounded by settings.media_max_bytes
  - sha256        String(64)  — hex digest for dedup + integrity
  - storage_path  String(1024) — server-local filesystem path
  - kind          String(64)  — passport_scan|visa_copy|
                                 booking_confirmation|hotel_voucher|
                                 flight_ticket|other
  - created_at    DateTime UTC NOT NULL default now()

Reversible: ``downgrade()`` drops the new columns and the
``message_attachments`` table.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as _PG_UUID
from sqlalchemy.types import CHAR, TypeDecorator


# Helper: same PortableUUID() factory the project uses elsewhere so the
# migration's UUID columns match the ORM's. Kept inline so this file is
# self-contained (no app import).
class PortableUUID(TypeDecorator):
    """UUID stored as native UUID on Postgres, CHAR(36) elsewhere.

    Mirrors the helper in ``app.models``; we duplicate it here so the
    migration file does not depend on importing app code (alembic env
    imports versions before app wiring is fully initialised).
    """
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return str(value)


revision: str = "0006_messages_attachments"
down_revision: Union[str, None] = "0005_user_onboarding_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Additive columns on ``messages`` (table created in 0002_messages)
    op.add_column(
        "messages",
        sa.Column(
            "is_summary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "booking_id",
            PortableUUID(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_messages_booking",
        "messages", "bookings_log",
        ["booking_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_messages_booking", "messages",
        ["booking_id"], unique=False,
    )

    # New table: message_attachments
    op.create_table(
        "message_attachments",
        sa.Column("id", PortableUUID(), primary_key=True),
        sa.Column(
            "message_id", PortableUUID(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_attachments_message", "message_attachments",
        ["message_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_message", table_name="message_attachments")
    op.drop_table("message_attachments")
    op.drop_index("ix_messages_booking", table_name="messages")
    op.drop_constraint("fk_messages_booking", "messages", type_="foreignkey")
    op.drop_column("messages", "booking_id")
    op.drop_column("messages", "is_summary")
"""Commerce + delivery + reports schema (2026-10-21).

- bookings_log: payment_status / paid_at / commission_cents (agent-pay
  flow; customers pay the agent off-platform, the app confirms).
- Partial unique index: at most one OPEN hand-off per itinerary
  (double-booking made structurally impossible).
- users: phone (global SMS), digest_optout + digest_last_sent_at
  (weekly auto-generated digest state).
- interests: is_active (admin taxonomy CRUD).
- digests table: the in-app copy of each weekly digest.
- permissions: report.read granted to admin + superadmin.

Revision ID: 0008_commerce_and_delivery
Revises: 0007_messages_attachments
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from app.models import PortableUUID as PortableUUIDType

revision: str = "0008_commerce_and_delivery"
down_revision: Union[str, None] = "0007_messages_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bookings_log",
        sa.Column(
            "payment_status",
            sa.String(16),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column("bookings_log", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "bookings_log",
        sa.Column("commission_cents", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index(
        "uq_bookings_log_active_one",
        "bookings_log",
        ["itinerary_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'claimed', 'in_progress')"),
    )

    op.add_column("users", sa.Column("phone", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column("digest_optout", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.add_column("users", sa.Column("digest_last_sent_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column(
        "interests",
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "digests",
        sa.Column("id", PortableUUIDType(), primary_key=True),
        sa.Column("user_id", PortableUUIDType(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_of", sa.Date, nullable=False),
        sa.Column("window", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("sent_email", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("email_status", sa.String(32), nullable=False, server_default="skipped"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_digests_user_week", "digests", ["user_id", "week_of"], unique=True)

    # report.read permission + grants (idempotent; uuids generated in-SQL
    # because pgcrypto/uuid-ossp are not installed on this database)
    op.execute(
        "INSERT INTO permissions (id, key, description) "
        "VALUES (md5(random()::text || clock_timestamp()::text)::uuid, 'report.read', "
        "'Read usage/trips/finance/resource reports') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r, permissions p "
        "WHERE p.key = 'report.read' AND r.name IN ('admin', 'superadmin') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id = (SELECT id FROM permissions WHERE key = 'report.read')"
    )
    op.execute("DELETE FROM permissions WHERE key = 'report.read'")
    op.drop_index("ix_digests_user_week", table_name="digests")
    op.drop_table("digests")
    op.drop_column("interests", "is_active")
    op.drop_column("users", "digest_last_sent_at")
    op.drop_column("users", "digest_optout")
    op.drop_column("users", "phone")
    op.drop_index("uq_bookings_log_active_one", table_name="bookings_log")
    op.drop_column("bookings_log", "commission_cents")
    op.drop_column("bookings_log", "paid_at")
    op.drop_column("bookings_log", "payment_status")
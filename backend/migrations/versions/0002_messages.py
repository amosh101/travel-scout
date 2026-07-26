"""messages table

Revision ID: 0002_messages
Revises: 0001_initial
Create Date: 2026-07-19

Concierge thread per saved itinerary. Used by /api/messages (POST + GET).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_messages"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    message_sender_role = sa.Enum(
        "user", "agent", "system", name="message_sender_role"
    )
    message_sender_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("itinerary_id", sa.String(length=36), nullable=False),
        sa.Column("sender_user_id", sa.String(length=36), nullable=False),
        sa.Column("sender_role", message_sender_role, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["itinerary_id"], ["saved_itineraries.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"], ["users.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_messages_itinerary", "messages",
        ["itinerary_id", "created_at"], unique=False,
    )
    op.create_index(
        "ix_messages_sender", "messages", ["sender_user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_messages_sender", table_name="messages")
    op.drop_index("ix_messages_itinerary", table_name="messages")
    op.drop_table("messages")
    sa.Enum(name="message_sender_role").drop(op.get_bind(), checkfirst=True)

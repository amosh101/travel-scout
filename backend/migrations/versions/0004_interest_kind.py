"""add kind column to interests

Revision ID: 0004_interest_kind
Revises: 0003_country_region
Create Date: 2026-07-19

The Interest catalog v3 groups interests into kinds (music, sport, food,
gaming, culture, lifestyle, holidays) so the intersection algorithm can
apply kind-level weights. The Python ``INTEREST_CATALOG`` is the source
of truth; this migration just adds the column.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_interest_kind"
down_revision = "0003_country_region"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "interests",
        sa.Column("kind", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interests", "kind")

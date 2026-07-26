"""user onboarding fields (T3 wizard persistence)

Revision ID: 0002_user_onboarding_fields
Revises: 0001_initial
Create Date: 2026-07-22

Adds 4 columns to ``users`` so POST /me/onboarding can round-trip via
GET /me:

- ``home_airport``           String(8)  nullable  (IATA 3-char, 8 leaves room)
- ``onboarding_complete``    Boolean    NOT NULL default False
- ``interests_json``         JSON       nullable  (wizard's interest keys)
- ``destinations_json``      JSON       nullable  (wizard's destination wishlist)

Existing rows get ``onboarding_complete=False`` (the table-level default),
``home_airport=NULL``, and ``interests_json=NULL`` / ``destinations_json=NULL``.
No backfill is required because the wizard did not write to the DB before
this migration (the audit-only behaviour was documented in t_83ea9222
attempt 2 and is replaced by real persistence here).

Reversible: ``downgrade()`` drops all 4 columns. No existing column is
altered.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_user_onboarding_fields"
down_revision: Union[str, None] = "0005_scraped"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("home_airport", sa.String(8), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "onboarding_complete",
            sa.Boolean,
            nullable=False,
            # Boolean default; sa.true() renders 'true' on Postgres
            # and '1' on SQLite. Earlier "0" integer default crashed
            # Postgres on boolean mismatch.
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("interests_json", sa.JSON, nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("destinations_json", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "destinations_json")
    op.drop_column("users", "interests_json")
    op.drop_column("users", "onboarding_complete")
    op.drop_column("users", "home_airport")

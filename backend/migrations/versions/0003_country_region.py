"""add region, sub_region, numeric_code to countries

Revision ID: 0003_country_region
Revises: 0002_messages
Create Date: 2026-07-19

The Country model has alpha2/alpha3/name/name_pt/currency/flag_emoji/
languages. To support the full ISO 3166-1 dataset (lukes/ISO-3166-
Countries-with-Regional-Codes) we add region, sub_region, and
numeric_code. These are nullable so existing rows are unaffected.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_country_region"
down_revision = "0002_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "countries",
        sa.Column("region", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "countries",
        sa.Column("sub_region", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "countries",
        sa.Column("numeric_code", sa.CHAR(length=3), nullable=True),
    )
    op.create_unique_constraint(
        "uq_cities_country_ascii", "cities",
        ["country_alpha2", "ascii_name"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_cities_country_ascii", "cities", type_="unique")
    op.drop_column("countries", "numeric_code")
    op.drop_column("countries", "sub_region")
    op.drop_column("countries", "region")

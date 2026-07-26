"""scraped_locations + scraped_events tables for the continuous scraper.

Revision ID: 0005_scraped
Revises: 0004_interest_kind
Create Date: 2026-07-20

The scraper (app/services/scraper/) runs as scheduled background jobs
that pull from Wikidata, Wikipedia, Nager.Date, Overpass, MusicBrainz
etc. and persist results into two tables:

  * ``scraped_locations`` — every place we've learned about from a
    free upstream. QID/GeoNames ID is the natural key, with
    (source, source_id) as the dedupe key per-source.

  * ``scraped_events`` — every event we've learned about. The
    ``dedupe_key`` is (source, source_id, year) so the same event
    recurring in different years doesn't get re-inserted, and the
    same year doesn't get re-inserted on re-scrape.

Both tables carry ``scraped_at`` (when we last refreshed) and
``expires_at`` (when the row should be considered stale if not
refreshed). The dedupe runs DELETE WHERE scraped_at < expires_at - 1d
on a daily cron.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005_scraped"
down_revision = "0004_interest_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # scraped_locations -----------------------------------------------------
    op.create_table(
        "scraped_locations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        # The natural key from the upstream — Wikidata QID, GeoNames ID,
        # OpenStreetMap relation/way ID, etc.
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("name_local", sa.String(length=512), nullable=True),
        sa.Column("country_alpha2", sa.CHAR(length=2), nullable=True),
        sa.Column("country_alpha3", sa.CHAR(length=3), nullable=True),
        sa.Column("country_numeric", sa.CHAR(length=3), nullable=True),
        sa.Column("subdivision_code", sa.String(length=16), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("wikidata_qid", sa.String(length=32), nullable=True),
        sa.Column("geonames_id", sa.Integer(), nullable=True),
        sa.Column("osm_id", sa.BigInteger(), nullable=True),
        sa.Column("feature_class", sa.String(length=16), nullable=True),
        sa.Column("feature_code", sa.String(length=32), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_id", name="uq_scraped_locations_source_id"),
    )
    op.create_index("ix_scraped_locations_country", "scraped_locations", ["country_alpha2"])
    op.create_index("ix_scraped_locations_wikidata", "scraped_locations", ["wikidata_qid"])
    op.create_index("ix_scraped_locations_geonames", "scraped_locations", ["geonames_id"])
    op.create_index("ix_scraped_locations_expires", "scraped_locations", ["expires_at"])

    # scraped_events --------------------------------------------------------
    op.create_table(
        "scraped_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("name_local", sa.String(length=512), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=True),
        sa.Column("interest_key", sa.String(length=64), nullable=True),
        sa.Column("starts_at", sa.Date(), nullable=True),
        sa.Column("ends_at", sa.Date(), nullable=True),
        sa.Column("recurring", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("scraped_locations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wikidata_qid", sa.String(length=32), nullable=True),
        sa.Column("raw", JSONB(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Dedup key: (source, source_id, year). Year is NULL for events
        # that don't have a year in the upstream payload (we then
        # dedup on (source, source_id) only by application logic).
        sa.Column("dedupe_year", sa.Integer(), nullable=True),
        sa.UniqueConstraint("source", "source_id", "dedupe_year", name="uq_scraped_events_dedupe"),
    )
    op.create_index("ix_scraped_events_interest", "scraped_events", ["interest_key", "starts_at"])
    op.create_index("ix_scraped_events_location", "scraped_events", ["location_id"])
    op.create_index("ix_scraped_events_starts", "scraped_events", ["starts_at"])
    op.create_index("ix_scraped_events_expires", "scraped_events", ["expires_at"])

    # scraped_runs ----------------------------------------------------------
    # Audit log of every scraper run — used to monitor health and to
    # detect when a source goes stale.
    op.create_table(
        "scraped_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("scraper", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),  # running|success|failed
        sa.Column("added", sa.Integer(), nullable=True),
        sa.Column("updated", sa.Integer(), nullable=True),
        sa.Column("removed", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index("ix_scraped_runs_source", "scraped_runs", ["source", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_scraped_runs_source", table_name="scraped_runs")
    op.drop_table("scraped_runs")
    op.drop_index("ix_scraped_events_expires", table_name="scraped_events")
    op.drop_index("ix_scraped_events_starts", table_name="scraped_events")
    op.drop_index("ix_scraped_events_location", table_name="scraped_events")
    op.drop_index("ix_scraped_events_interest", table_name="scraped_events")
    op.drop_table("scraped_events")
    op.drop_index("ix_scraped_locations_expires", table_name="scraped_locations")
    op.drop_index("ix_scraped_locations_geonames", table_name="scraped_locations")
    op.drop_index("ix_scraped_locations_wikidata", table_name="scraped_locations")
    op.drop_index("ix_scraped_locations_country", table_name="scraped_locations")
    op.drop_table("scraped_locations")

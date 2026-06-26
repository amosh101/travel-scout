"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-26

All v2 foundation tables. Manually authored (autogenerate produces a near-empty
file on SQLite for portable JSON columns); see ``app/models/__init__.py`` for
the matching ORM definitions.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    subscription_tier = sa.Enum(
        "free", "limited", "unlimited", "concierge", name="subscription_tier"
    )
    subscription_status = sa.Enum(
        "trialing", "active", "past_due", "canceled", name="subscription_status"
    )
    actor_kind = sa.Enum("user", "admin", "agent", "system", name="actor_kind")
    interest_priority = sa.Enum("low", "medium", "high", name="interest_priority")

    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("tier", subscription_tier, nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_tier", "users", ["tier"])
    op.create_index("ix_users_active", "users", ["is_active"])

    op.create_table(
        "roles",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "permissions",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.CHAR(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.CHAR(36), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.CHAR(36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_by", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "interests",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("event_keywords", sa.JSON, nullable=False),
        sa.Column("destination_region", sa.String(64), nullable=True),
        sa.Column("destination_flexibility", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "destinations",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("iata_code", sa.CHAR(3), nullable=True, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("country", sa.String(64), nullable=False),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("latitude", sa.String(32), nullable=True),
        sa.Column("longitude", sa.String(32), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "user_interests",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interest_id", sa.CHAR(36), sa.ForeignKey("interests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority", interest_priority, nullable=False, server_default="medium"),
        sa.Column("origin_airport", sa.CHAR(3), nullable=True),
        sa.Column("destination_flexibility", sa.String(32), nullable=True),
        sa.Column("max_budget_cents", sa.Integer, nullable=True),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "interest_id", name="uq_user_interest"),
    )
    op.create_index("ix_user_interests_user", "user_interests", ["user_id"])

    op.create_table(
        "event_sources",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("auth_env_var", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "events",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("source_id", sa.CHAR(36), sa.ForeignKey("event_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_event_id", sa.String(255), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("destination_id", sa.CHAR(36), sa.ForeignKey("destinations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "source_event_id", name="uq_event_source"),
    )
    op.create_index("ix_events_starts_at", "events", ["starts_at"])
    op.create_index("ix_events_destination", "events", ["destination_id"])
    op.create_index("ix_events_category", "events", ["category"])

    op.create_table(
        "flight_sources",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("auth_env_var", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "flight_offers",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("source_id", sa.CHAR(36), sa.ForeignKey("flight_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("origin", sa.CHAR(3), nullable=False),
        sa.Column("destination", sa.CHAR(3), nullable=False),
        sa.Column("depart_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("return_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="USD"),
        sa.Column("airline", sa.String(64), nullable=True),
        sa.Column("deep_link", sa.String(1024), nullable=True),
        sa.Column("raw", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_flight_offers_route", "flight_offers", ["origin", "destination", "depart_date"])
    op.create_index("ix_flight_offers_depart", "flight_offers", ["depart_date"])

    op.create_table(
        "saved_itineraries",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("destination_id", sa.CHAR(36), sa.ForeignKey("destinations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("total_price_cents", sa.Integer, nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="USD"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_saved_itineraries_user", "saved_itineraries", ["user_id"])

    op.create_table(
        "bookings_log",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("itinerary_id", sa.CHAR(36), sa.ForeignKey("saved_itineraries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.CHAR(3), nullable=False, server_default="USD"),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_bookings_log_user", "bookings_log", ["user_id"])
    op.create_index("ix_bookings_log_status", "bookings_log", ["status"])

    op.create_table(
        "algo_weights",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_by", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_sub_id", sa.String(255), nullable=False, unique=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=False, unique=True),
        sa.Column("tier", subscription_tier, nullable=False, server_default="free"),
        sa.Column("status", subscription_status, nullable=False, server_default="trialing"),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subscriptions_user", "subscriptions", ["user_id"])

    op.create_table(
        "stripe_events",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("stripe_event_id", sa.String(255), nullable=False, unique=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("actor_user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_kind", actor_kind, nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("target_kind", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_at", "audit_log", ["at"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_user_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    op.create_table(
        "tier_limits",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("tier", subscription_tier, nullable=False, unique=True),
        sa.Column("max_saved_per_month", sa.Integer, nullable=False),
        sa.Column("max_searches_per_month", sa.Integer, nullable=False),
        sa.Column("has_agent", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "usage_counters",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("user_id", sa.CHAR(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_yyyymm", sa.Integer, nullable=False),
        sa.Column("saves", sa.Integer, nullable=False, server_default="0"),
        sa.Column("searches", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "period_yyyymm", name="uq_usage_period"),
    )
    op.create_index("ix_usage_user_period", "usage_counters", ["user_id", "period_yyyymm"])


def downgrade() -> None:
    # Drop in reverse dependency order
    for tbl in [
        "usage_counters", "tier_limits", "audit_log", "stripe_events",
        "subscriptions", "algo_weights", "bookings_log", "saved_itineraries",
        "flight_offers", "flight_sources", "events", "event_sources",
        "user_interests", "destinations", "interests", "user_roles",
        "role_permissions", "permissions", "roles", "users",
    ]:
        op.drop_table(tbl)
    sa.Enum(name="subscription_tier").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="subscription_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="actor_kind").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="interest_priority").drop(op.get_bind(), checkfirst=True)
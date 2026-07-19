"""SQLAlchemy ORM models for Travel Scout v2.

Schema design notes:
- All primary keys are UUID v4 (portable, no info-leak via sequential IDs).
- All tables have ``created_at`` + ``updated_at`` where stateful.
- All FKs declare explicit ON DELETE behaviour.
- All hot-path WHERE columns get an index (see ``__table_args__``).
- No booleans for permission flags — string permissions + a join table.
- JSON columns (e.g. ``event_keywords``) are portable: JSONB on Postgres,
  JSON on SQLite.
- Reference data (roles, permissions, interests, destinations) is NOT seeded
  via SQLAlchemy defaults; it's loaded by ``scripts/seed_reference``.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CHAR,
    Column,
    Date as SA_Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PortableUUID
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, relationship

from app.database import Base
from app.models.types import (
    PortableUUID,
    created_at_column,
    updated_at_column,
    uuid_pk_column,
)


# -----------------------------------------------------------------------------
# Enums (DB-side via Enum, application-side via Python enum)
# -----------------------------------------------------------------------------

class SubscriptionTier(str, enum.Enum):
    FREE = "free"
    LIMITED = "limited"
    UNLIMITED = "unlimited"
    CONCIERGE = "concierge"


class SubscriptionStatus(str, enum.Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class ActorKind(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"
    AGENT = "agent"
    SYSTEM = "system"


class InterestPriority(int, enum.Enum):
    LOW = 3
    MEDIUM = 2
    HIGH = 1


# -----------------------------------------------------------------------------
# Portable JSON column helper
# -----------------------------------------------------------------------------

def portable_json() -> Any:
    """JSONB on Postgres, JSON on SQLite (handled at dialect level)."""
    return JSON


# -----------------------------------------------------------------------------
# Users
# -----------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = uuid_pk_column()
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False, default="")
    is_active = Column(Boolean, nullable=False, default=True)
    tier = Column(
        Enum(SubscriptionTier, name="subscription_tier"),
        nullable=False,
        default=SubscriptionTier.FREE,
    )
    stripe_customer_id = Column(String(255), nullable=True, unique=True)

    # --- T8f: travel-doc / contact fields (all nullable, all optional) ---
    # Nationality and passport-issuing country are ISO 3166-1 alpha-2.
    nationality = Column(String(2), nullable=True)
    passport_number = Column(String(512), nullable=True)  # T8f: obfuscated
    passport_expiry = Column(SA_Date, nullable=True)
    passport_issuing_country = Column(String(2), nullable=True)
    date_of_birth = Column(SA_Date, nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(32), nullable=True)

    created_at = created_at_column()
    updated_at = updated_at_column()

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user",
        foreign_keys="UserRole.user_id",
        primaryjoin="User.id == UserRole.user_id",
    )
    interests: Mapped[list["UserInterest"]] = relationship(back_populates="user")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="user")

    __table_args__ = (
        Index("ix_users_tier", "tier"),
        Index("ix_users_active", "is_active"),
    )


# -----------------------------------------------------------------------------
# Roles + Permissions (NOT boolean)
# -----------------------------------------------------------------------------

class Role(Base):
    __tablename__ = "roles"

    id = uuid_pk_column()
    key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False, default="")

    created_at = created_at_column()

    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")
    users: Mapped[list["UserRole"]] = relationship(back_populates="role")


class Permission(Base):
    __tablename__ = "permissions"

    id = uuid_pk_column()
    key = Column(String(128), nullable=False, unique=True)
    description = Column(Text, nullable=False, default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id = Column(
        PortableUUID(),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id = Column(
        PortableUUID(),
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    permission: Mapped[Permission] = relationship()


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id = Column(
        PortableUUID(),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    granted_by = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(
        back_populates="roles",
        foreign_keys=[user_id],
        primaryjoin="UserRole.user_id == User.id",
    )
    role: Mapped[Role] = relationship(back_populates="users")
    granter: Mapped[User | None] = relationship(
        foreign_keys=[granted_by],
        primaryjoin="UserRole.granted_by == User.id",
    )


# -----------------------------------------------------------------------------
# Reference data (interests catalog, destinations)
# -----------------------------------------------------------------------------

class Interest(Base):
    """Catalog of interest categories — seeded by ``seed_reference``.

    v1 carried: ``event_keywords`` list, ``destination_region``,
    ``destination_flexibility``. v2 keeps the same shape.
    """
    __tablename__ = "interests"

    id = uuid_pk_column()
    key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False, default="")
    event_keywords = Column(portable_json(), nullable=False, default=list)
    destination_region = Column(String(64), nullable=True)
    destination_flexibility = Column(String(32), nullable=True)  # strict | flexible | anywhere

    created_at = created_at_column()

    user_interests: Mapped[list["UserInterest"]] = relationship(back_populates="interest")


class Destination(Base):
    """Reference destinations for travel recommendations."""
    __tablename__ = "destinations"

    id = uuid_pk_column()
    iata_code = Column(CHAR(3), nullable=True, unique=True)
    name = Column(String(255), nullable=False)
    country = Column(String(64), nullable=False)
    region = Column(String(64), nullable=True)
    latitude = Column(String(32), nullable=True)
    longitude = Column(String(32), nullable=True)
    timezone = Column(String(64), nullable=True)

    created_at = created_at_column()


class UserInterest(Base):
    """Join: user has many interest categories with personal weights."""
    __tablename__ = "user_interests"

    id = uuid_pk_column()
    user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    interest_id = Column(
        PortableUUID(),
        ForeignKey("interests.id", ondelete="CASCADE"),
        nullable=False,
    )
    priority = Column(
        Enum(InterestPriority, name="interest_priority"),
        nullable=False,
        default=InterestPriority.MEDIUM,
    )
    origin_airport = Column(CHAR(3), nullable=True)
    destination_flexibility = Column(String(32), nullable=True)
    max_budget_cents = Column(Integer, nullable=True)
    notes = Column(Text, nullable=False, default="")

    created_at = created_at_column()
    updated_at = updated_at_column()

    user: Mapped[User] = relationship(back_populates="interests")
    interest: Mapped[Interest] = relationship(back_populates="user_interests")

    __table_args__ = (
        UniqueConstraint("user_id", "interest_id", name="uq_user_interest"),
        Index("ix_user_interests_user", "user_id"),
    )


# -----------------------------------------------------------------------------
# Events + flight offers
# -----------------------------------------------------------------------------

class EventSource(Base):
    """Source registry for event feeds (Ticketmaster, Jolpica, etc.)."""
    __tablename__ = "event_sources"

    id = uuid_pk_column()
    key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    base_url = Column(String(512), nullable=False)
    auth_env_var = Column(String(64), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = created_at_column()


class Event(Base):
    """An event (concert, race, exhibition) discovered from a source."""
    __tablename__ = "events"

    id = uuid_pk_column()
    source_id = Column(
        PortableUUID(),
        ForeignKey("event_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_event_id = Column(String(255), nullable=False)
    title = Column(String(512), nullable=False)
    category = Column(String(64), nullable=True)
    destination_id = Column(
        PortableUUID(),
        ForeignKey("destinations.id", ondelete="SET NULL"),
        nullable=True,
    )
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    url = Column(String(1024), nullable=True)
    metadata_json = Column("metadata", portable_json(), nullable=False, default=dict)

    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        UniqueConstraint("source_id", "source_event_id", name="uq_event_source"),
        Index("ix_events_starts_at", "starts_at"),
        Index("ix_events_destination", "destination_id"),
        Index("ix_events_category", "category"),
    )


class FlightSource(Base):
    """Source registry for flight data feeds."""
    __tablename__ = "flight_sources"

    id = uuid_pk_column()
    key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    base_url = Column(String(512), nullable=False)
    auth_env_var = Column(String(64), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)

    created_at = created_at_column()


class FlightOffer(Base):
    """Cached flight offer."""
    __tablename__ = "flight_offers"

    id = uuid_pk_column()
    source_id = Column(
        PortableUUID(),
        ForeignKey("flight_sources.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin = Column(CHAR(3), nullable=False)
    destination = Column(CHAR(3), nullable=False)
    depart_date = Column(DateTime(timezone=True), nullable=False)
    return_date = Column(DateTime(timezone=True), nullable=True)
    price_cents = Column(Integer, nullable=False)
    currency = Column(CHAR(3), nullable=False, default="USD")
    airline = Column(String(64), nullable=True)
    deep_link = Column(String(1024), nullable=True)
    raw_json = Column("raw", portable_json(), nullable=False, default=dict)

    created_at = created_at_column()

    __table_args__ = (
        Index("ix_flight_offers_route", "origin", "destination", "depart_date"),
        Index("ix_flight_offers_depart", "depart_date"),
    )


# -----------------------------------------------------------------------------
# Saved itineraries + bookings
# -----------------------------------------------------------------------------

class SavedItinerary(Base):
    """A user-saved intersection result (events + flights + day plan)."""
    __tablename__ = "saved_itineraries"

    id = uuid_pk_column()
    user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    destination_id = Column(
        PortableUUID(),
        ForeignKey("destinations.id", ondelete="SET NULL"),
        nullable=True,
    )
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(portable_json(), nullable=False, default=dict)
    total_price_cents = Column(Integer, nullable=True)
    currency = Column(CHAR(3), nullable=False, default="USD")

    created_at = created_at_column()
    updated_at = updated_at_column()

    __table_args__ = (
        Index("ix_saved_itineraries_user", "user_id"),
    )


class BookingsLog(Base):
    """Append-only booking attempts log (financial trail)."""
    __tablename__ = "bookings_log"

    id = uuid_pk_column()
    user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    itinerary_id = Column(
        PortableUUID(),
        ForeignKey("saved_itineraries.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String(32), nullable=False)  # pending | claimed | in_progress | confirmed | failed | refunded
    amount_cents = Column(Integer, nullable=False, default=0)
    currency = Column(CHAR(3), nullable=False, default="USD")
    external_id = Column(String(255), nullable=True)  # Stripe charge / booking ref
    metadata_json = Column("metadata", portable_json(), nullable=False, default=dict)
    # T8e: agent-handoff fields. Nullable so the existing rows are
    # valid; ``create_all`` will add the new columns on next boot.
    assigned_agent_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    outcome_at = Column(DateTime(timezone=True), nullable=True)
    outcome_note = Column(Text, nullable=True)

    created_at = created_at_column()

    __table_args__ = (
        Index("ix_bookings_log_user", "user_id"),
        Index("ix_bookings_log_status", "status"),
        Index("ix_bookings_log_agent", "assigned_agent_id"),
    )


# -----------------------------------------------------------------------------
# Algo weights (admin-tunable scoring parameters)
# -----------------------------------------------------------------------------

class AlgoWeight(Base):
    """Tunable weights for the intersection scoring algorithm.

    v2 starts with sane defaults; admins adjust via /api/admin/weights.
    """
    __tablename__ = "algo_weights"

    id = uuid_pk_column()
    key = Column(String(64), nullable=False, unique=True)
    value = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    updated_by = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# -----------------------------------------------------------------------------
# Subscriptions (Stripe)
# -----------------------------------------------------------------------------

class Subscription(Base):
    """Mirrors Stripe subscription state. Source of truth for tier."""
    __tablename__ = "subscriptions"

    id = uuid_pk_column()
    user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    stripe_sub_id = Column(String(255), nullable=False, unique=True)
    stripe_customer_id = Column(String(255), nullable=False, unique=True)
    tier = Column(
        Enum(SubscriptionTier, name="subscription_tier"),
        nullable=False,
        default=SubscriptionTier.FREE,
    )
    status = Column(
        Enum(SubscriptionStatus, name="subscription_status"),
        nullable=False,
        default=SubscriptionStatus.TRIALING,
    )
    current_period_end = Column(DateTime(timezone=True), nullable=True)

    created_at = created_at_column()
    updated_at = updated_at_column()

    user: Mapped[User] = relationship(back_populates="subscriptions")

    __table_args__ = (
        Index("ix_subscriptions_user", "user_id"),
    )


class StripeEvent(Base):
    """Idempotency record for Stripe webhook events."""
    __tablename__ = "stripe_events"

    id = uuid_pk_column()
    stripe_event_id = Column(String(255), nullable=False, unique=True)
    event_type = Column(String(128), nullable=False)
    payload = Column(portable_json(), nullable=False, default=dict)
    received_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)


# -----------------------------------------------------------------------------
# Audit log + tier limits + usage counters
# -----------------------------------------------------------------------------

class AuditLog(Base):
    """Append-only audit trail of privileged actions."""
    __tablename__ = "audit_log"

    id = uuid_pk_column()
    actor_user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_kind = Column(
        Enum(ActorKind, name="actor_kind"),
        nullable=False,
    )
    action = Column(String(128), nullable=False)
    target_kind = Column(String(64), nullable=True)
    target_id = Column(String(64), nullable=True)
    metadata_json = Column("metadata", portable_json(), nullable=False, default=dict)
    request_id = Column(String(64), nullable=True)
    at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_audit_log_at", "at"),
        Index("ix_audit_log_actor", "actor_user_id"),
        Index("ix_audit_log_action", "action"),
    )


class TierLimit(Base):
    """Per-tier rate limits and feature flags. Seeded by ``seed_reference``."""
    __tablename__ = "tier_limits"

    id = uuid_pk_column()
    tier = Column(
        Enum(SubscriptionTier, name="subscription_tier"),
        nullable=False,
        unique=True,
    )
    max_saved_per_month = Column(Integer, nullable=False)
    max_searches_per_month = Column(Integer, nullable=False)
    has_agent = Column(Boolean, nullable=False, default=False)


class UsageCounter(Base):
    """Per-user, per-period usage tracking for tier guards."""
    __tablename__ = "usage_counters"

    id = uuid_pk_column()
    user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_yyyymm = Column(Integer, nullable=False)  # e.g. 202606
    saves = Column(Integer, nullable=False, default=0)
    searches = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "period_yyyymm", name="uq_usage_period"),
        Index("ix_usage_user_period", "user_id", "period_yyyymm"),
    )


# Re-export all models for convenient import from ``app.models``
# -----------------------------------------------------------------------------
# Messages (concierge thread per itinerary)
# -----------------------------------------------------------------------------
# The user (or their assigned concierge agent) can post messages attached
# to a SavedItinerary. Read by polling GET /api/messages?itinerary_id=...
# sender_role: who sent it. Free-tier users can't post (require_tier
# concierge); agents (role.agent) and the user themselves (role.user)
# are the only valid senders.

class MessageSenderRole(str, Enum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


# Build a string-based SA Enum so SQLAlchemy can introspect length/etc.
# without hitting the str+Enum mixin's TypeError.
_MESSAGE_SENDER_ROLE_SA = Enum(
    "user", "agent", "system", name="message_sender_role"
)


class Message(Base):
    __tablename__ = "messages"

    id = uuid_pk_column()
    itinerary_id = Column(
        PortableUUID(),
        ForeignKey("saved_itineraries.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_user_id = Column(
        PortableUUID(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    sender_role = Column(
        _MESSAGE_SENDER_ROLE_SA,
        nullable=False,
    )
    body = Column(Text, nullable=False)
    created_at = created_at_column()

    __table_args__ = (
        Index("ix_messages_itinerary", "itinerary_id", "created_at"),
        Index("ix_messages_sender", "sender_user_id"),
    )


# Refdata models (countries, cities, airports, city_aliases) live in
# ``app.refdata.models`` to keep this file focused on the core domain.
#
# DO NOT import them here: ``app.refdata.models`` imports the type
# helpers from this file (PortableUUID etc.), which would create a
# partial-load cycle. Refdata models register on Base.metadata the
# first time anything imports ``app.refdata.models`` (the search router,
# the refdata router, the seed script, etc.), so the side-effect
# registration happens naturally.

__all__ = [
    "ActorKind",
    "Airport",
    "AlgoWeight",
    "AuditLog",
    "BookingsLog",
    "City",
    "CityAlias",
    "Country",
    "Destination",
    "Event",
    "EventSource",
    "FlightOffer",
    "FlightSource",
    "Interest",
    "InterestPriority",
    "Message",
    "MessageSenderRole",
    "Permission",
    "Role",
    "RolePermission",
    "SavedItinerary",
    "StripeEvent",
    "Subscription",
    "SubscriptionStatus",
    "SubscriptionTier",
    "TierLimit",
    "UsageCounter",
    "User",
    "UserInterest",
    "UserRole",
]
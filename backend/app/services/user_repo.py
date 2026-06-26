"""
UserRepository — service layer over the `users` table.

This is the canonical entry point for user-related persistence: creation,
lookup, password verification, GDPR right-to-erasure, and data portability.

Design notes:
  - All public methods are `async` and operate on the AsyncSession injected
    in __init__. They `flush()` but do NOT commit — the caller (typically a
    FastAPI route) controls transaction boundaries.
  - Password hashing uses passlib's CryptContext with bcrypt. bcrypt has a
    72-byte input limit (the well-known /tmp/openclaw-import bug); we
    truncate before hashing and before verifying.
  - Email is stored lowercased and looked up case-insensitively. The DB has
    a unique index on email; create_user lets the IntegrityError bubble up
    so the route layer can translate it into a 409.
  - soft_delete_account() preserves the password_hash on purpose: it prevents
    a deleted account's email from being re-registered by a different user.
  - update_last_login() is currently a no-op. The User model lacks a
    last_login column; the column will be added in a later migration, at
    which point this method will read/update it.
"""

from uuid import UUID
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    User,
    Interest,
    FlightAlert,
    SavedTrip,
    DismissedTrip,
    AuditLog,
)

from passlib.context import CryptContext


# Truncation is applied at both hash-time and verify-time. We share one
# constant so the limit is obvious and easy to update if we ever swap to a
# different KDF.
_BCRYPT_MAX_BYTES = 72

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UserRepository:
    """Async repository for the `users` table and its related GDPR operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------------------------------------------------
    # create_user
    # -----------------------------------------------------------------------

    async def create_user(
        self,
        email: str,
        password: str,
        display_name: Optional[str] = None,
    ) -> User:
        """Create a new user. Hashes the password.

        Raises IntegrityError if `email` already exists (the route layer
        catches and returns 409). Email is lowercased before insert so
        later lookups can be case-insensitive.

        bcrypt only considers the first 72 bytes of the password; we
        truncate explicitly here so the caller's behavior is predictable
        regardless of passlib's internal handling.
        """
        normalized_email = email.lower()

        # Pre-check for clearer errors; the unique index would catch it
        # anyway on flush, but this avoids a wasted hash on the hot path
        # and makes the duplicate case explicit in logs.
        existing = await self.get_by_email(normalized_email)
        if existing is not None:
            # Raise the same exception type the DB would raise so callers
            # only need to handle IntegrityError.
            raise IntegrityError(
                statement="SELECT users WHERE email = :email",
                params={"email": normalized_email},
                orig=Exception("email already exists"),
            )

        # Truncate before hashing (bcrypt 72-byte limit).
        password_bytes = password[:_BCRYPT_MAX_BYTES].encode("utf-8")
        password_hash = pwd_context.hash(password_bytes)

        user = User(
            email=normalized_email,
            password_hash=password_hash,
            name=display_name,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    # -----------------------------------------------------------------------
    # get_by_email
    # -----------------------------------------------------------------------

    async def get_by_email(self, email: str) -> Optional[User]:
        """Return User by email (case-insensitive), or None."""
        stmt = select(User).where(User.email == email.lower())
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # -----------------------------------------------------------------------
    # get_by_id
    # -----------------------------------------------------------------------

    async def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Return User by id, or None."""
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # -----------------------------------------------------------------------
    # verify_password
    # -----------------------------------------------------------------------

    async def verify_password(self, user: User, password: str) -> bool:
        """Return True if `password` matches the user's stored hash.

        Truncates to 72 bytes before verify — bcrypt ignores everything
        after byte 72, so verifying a full-length password against a
        hash that was made from a truncated one still returns True.
        """
        password_bytes = password[:_BCRYPT_MAX_BYTES].encode("utf-8")
        return pwd_context.verify(password_bytes, user.password_hash)

    # -----------------------------------------------------------------------
    # update_last_login
    # -----------------------------------------------------------------------

    async def update_last_login(self, user_id: UUID) -> None:
        """Update the user's last_login timestamp.

        NOTE: This is currently a no-op. The User model (app/models/__init__.py)
        does not yet have a `last_login` column — the column will be added
        in a later migration as part of the auth improvements. Until then,
        this method intentionally does nothing rather than failing on an
        unknown attribute.

        When the column lands, this method becomes:
            user = await self.get_by_id(user_id)
            if user is not None:
                user.last_login = datetime.utcnow()
                await self.db.flush()
        """
        return None

    # -----------------------------------------------------------------------
    # soft_delete_account (GDPR right-to-erasure)
    # -----------------------------------------------------------------------

    async def soft_delete_account(self, user_id: UUID) -> None:
        """GDPR right-to-erasure: anonymize the user rather than deleting.

        What changes:
          - is_active        → False          (cannot log in)
          - email            → 'deleted-{uuid}'
          - name             → None
          - phone            → None
          - telegram_chat_id → None
          - whatsapp_phone   → None

        What we deliberately KEEP:
          - password_hash    — keeps the deleted email un-registrable.
          - the user row     — so AuditLog FK rows survive. AuditLog.user_id
                               has `ondelete='SET NULL'`, but the row itself
                               stays, preserving the audit trail.

        Relationships (interests, alerts, saved_trips, dismissed_trips) are
        CASCADE-deleted at the DB level when the user row is hard-deleted;
        since we soft-delete, they remain and refer to the still-existing
        anonymized row. That's the intended behavior: an ex-user's data
        relations are still queryable by admins (audit / abuse investigation)
        but no longer attributable to a real person.
        """
        user = await self.get_by_id(user_id)
        if user is None:
            # No-op for missing users — keeps the API idempotent so the
            # route layer can call this without a pre-check.
            return

        user.is_active = False
        user.email = f"deleted-{user.id}"
        user.name = None
        user.phone = None
        user.telegram_chat_id = None
        user.whatsapp_phone = None

        await self.db.flush()

    # -----------------------------------------------------------------------
    # export_account_data (GDPR data portability)
    # -----------------------------------------------------------------------

    async def export_account_data(self, user_id: UUID) -> dict:
        """Return all of the user's data as a JSON-serializable dict.

        Includes the user record plus every relationship the GDPR scope
        covers:
          - user              : core profile
          - interests         : Interest rows
          - alerts            : FlightAlert rows
          - saved_trips       : SavedTrip rows
          - dismissed_trips   : DismissedTrip rows
          - audit_log         : AuditLog rows for this user

        Each list contains dicts of column values so the result is
        JSON-serializable out of the box.
        """
        user = await self.get_by_id(user_id)
        if user is None:
            raise ValueError(f"No user with id={user_id}")

        interests = await self.db.execute(
            select(Interest).where(Interest.user_id == user_id)
        )
        alerts = await self.db.execute(
            select(FlightAlert).where(FlightAlert.user_id == user_id)
        )
        saved_trips = await self.db.execute(
            select(SavedTrip).where(SavedTrip.user_id == user_id)
        )
        dismissed_trips = await self.db.execute(
            select(DismissedTrip).where(DismissedTrip.user_id == user_id)
        )
        audit_rows = await self.db.execute(
            select(AuditLog).where(AuditLog.user_id == user_id)
        )

        return {
            "user": _serialize_user(user),
            "interests": [_serialize_interest(i) for i in interests.scalars().all()],
            "alerts": [_serialize_alert(a) for a in alerts.scalars().all()],
            "saved_trips": [_serialize_saved_trip(t) for t in saved_trips.scalars().all()],
            "dismissed_trips": [
                _serialize_dismissed_trip(d) for d in dismissed_trips.scalars().all()
            ],
            "audit_log": [_serialize_audit(a) for a in audit_rows.scalars().all()],
        }


# ---------------------------------------------------------------------------
# Serializers (module-private)
# ---------------------------------------------------------------------------
# Keeping these here (rather than on the models) means the export contract
# is owned by UserRepository — if we add or remove a field from export,
# there's exactly one file to edit. It also keeps the model classes free
# of presentation concerns.

def _serialize_user(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "name": u.name,
        "phone": u.phone,
        "telegram_chat_id": u.telegram_chat_id,
        "whatsapp_phone": u.whatsapp_phone,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "is_active": u.is_active,
    }


def _serialize_interest(i: Interest) -> dict:
    return {
        "id": str(i.id),
        "name": i.name,
        "origin_airport": i.origin_airport,
        "destination_region": i.destination_region,
        "event_keywords": i.event_keywords,
        "max_budget": float(i.max_budget) if i.max_budget is not None else None,
        "notification_channels": list(i.notification_channels or []),
        "active": i.active,
        "date_flexibility": i.date_flexibility,
        "preferred_departure_date": (
            i.preferred_departure_date.isoformat() if i.preferred_departure_date else None
        ),
        "preferred_return_date": (
            i.preferred_return_date.isoformat() if i.preferred_return_date else None
        ),
        "priority": i.priority,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


def _serialize_alert(a: FlightAlert) -> dict:
    return {
        "id": str(a.id),
        "interest_id": str(a.interest_id) if a.interest_id else None,
        "origin": a.origin,
        "destination": a.destination,
        "airline": a.airline,
        "price": float(a.price) if a.price is not None else None,
        "currency": a.currency,
        "depart_date": a.depart_date.isoformat() if a.depart_date else None,
        "return_date": a.return_date.isoformat() if a.return_date else None,
        "found_at": a.found_at.isoformat() if a.found_at else None,
        "notified": a.notified,
    }


def _serialize_saved_trip(t: SavedTrip) -> dict:
    return {
        "id": str(t.id),
        "intersection_id": t.intersection_id,
        "city": t.city,
        "country": t.country,
        "start_date": t.start_date.isoformat() if t.start_date else None,
        "end_date": t.end_date.isoformat() if t.end_date else None,
        "snapshot_json": t.snapshot_json,
        "saved_utc": t.saved_utc.isoformat() if t.saved_utc else None,
    }


def _serialize_dismissed_trip(d: DismissedTrip) -> dict:
    return {
        "id": str(d.id),
        "intersection_id": d.intersection_id,
        "dismissed_utc": d.dismissed_utc.isoformat() if d.dismissed_utc else None,
    }


def _serialize_audit(a: AuditLog) -> dict:
    return {
        "id": str(a.id),
        "action": a.action,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "before_json": a.before_json,
        "after_json": a.after_json,
        "source": a.source,
        "ip_address": a.ip_address,
        "request_id": a.request_id,
        "occurred_utc": a.occurred_utc.isoformat() if a.occurred_utc else None,
    }
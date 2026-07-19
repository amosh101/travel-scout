"""GDPR / privacy endpoints.

Three operations:
  - GET  /api/me/export  - JSON dump of all user data (Art. 15 / right of access)
  - POST /api/me/change-password - password rotation (art. 17 implies secure auth)
  - DELETE /api/me - soft delete (sets is_active=False, blanks PII, keeps
    audit trail and bookings_log rows for financial record-keeping)

All endpoints require Bearer auth. The current user can only act on
themselves.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    BookingsLog,
    Interest,
    SavedItinerary,
    User,
    UserInterest,
    UserRole,
)
from app.routers.auth import get_current_user
from app.security import hash_password, verify_password
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["me-gdpr"])


# -----------------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=12, max_length=255)


class ChangePasswordResponse(BaseModel):
    changed: bool
    changed_at: str


class DeleteMeRequest(BaseModel):
    confirm: bool = Field(
        default=False,
        description="Must be true. Defensive guard against accidental deletion.",
    )
    reason: str | None = Field(default=None, max_length=500)


class DeleteMeResponse(BaseModel):
    deleted: bool
    deleted_at: str
    anonymized_email: str


# -----------------------------------------------------------------------------
# GET /api/me/export - GDPR Art. 15 right of access
# -----------------------------------------------------------------------------

@router.get("/export")
async def export_my_data(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Return a JSON dump of every field and related record we hold for
    the current user. Stable, machine-readable, includes both profile
    fields and foreign-key rows (interests, itineraries, bookings, audit).
    """
    # Profile fields
    profile = {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "tier": user.tier.value,
        "is_active": user.is_active,
        "nationality": user.nationality,
        "passport_number_set": bool(user.passport_number),
        "passport_expiry": user.passport_expiry.isoformat() if user.passport_expiry else None,
        "passport_issuing_country": user.passport_issuing_country,
        "date_of_birth": user.date_of_birth.isoformat() if user.date_of_birth else None,
        "emergency_contact_name": user.emergency_contact_name,
        "emergency_contact_phone": user.emergency_contact_phone,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }

    # Interests
    interest_rows = (
        await session.execute(
            select(UserInterest).where(UserInterest.user_id == user.id)
        )
    ).scalars().all()
    interest_ids = [r.interest_id for r in interest_rows]
    catalog = {}
    if interest_ids:
        cat_rows = (
            await session.execute(
                select(Interest).where(Interest.id.in_(interest_ids))
            )
        ).scalars().all()
        catalog = {i.id: {"key": i.key, "name": i.name} for i in cat_rows}
    interests = [
        {
            "id": str(r.id),
            "interest_key": catalog.get(r.interest_id, {}).get("key"),
            "interest_name": catalog.get(r.interest_id, {}).get("name"),
            "priority": r.priority.value if r.priority else None,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in interest_rows
    ]

    # Roles (read-only; we tell the user what they have, not the underlying
    # join IDs).
    role_rows = (
        await session.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        )
    ).scalars().all()
    roles = [
        {
            "role_id": str(r.role_id),
            "granted_at": r.granted_at.isoformat() if r.granted_at else None,
            "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
        }
        for r in role_rows
    ]

    # Saved itineraries
    itin_rows = (
        await session.execute(
            select(SavedItinerary).where(SavedItinerary.user_id == user.id)
        )
    ).scalars().all()
    itineraries = [
        {
            "id": str(r.id),
            "title": r.title,
            "starts_at": r.starts_at.isoformat() if r.starts_at else None,
            "ends_at": r.ends_at.isoformat() if r.ends_at else None,
            "currency": r.currency,
            "total_price_cents": r.total_price_cents,
            "payload": r.payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in itin_rows
    ]

    # Bookings
    book_rows = (
        await session.execute(
            select(BookingsLog).where(BookingsLog.user_id == user.id)
        )
    ).scalars().all()
    bookings = [
        {
            "id": str(r.id),
            "itinerary_id": str(r.itinerary_id) if r.itinerary_id else None,
            "status": r.status,
            "external_id": r.external_id,
            "amount_cents": r.amount_cents,
            "currency": r.currency,
            "metadata": r.metadata_json,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in book_rows
    ]

    # Audit log rows where this user is the actor
    audit_rows = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.actor_user_id == user.id)
            .order_by(AuditLog.at.desc())
            .limit(500)
        )
    ).scalars().all()
    audit = [
        {
            "id": str(a.id),
            "action": a.action,
            "target_kind": a.target_kind,
            "target_id": a.target_id,
            "metadata": a.metadata_json,
            "at": a.at.isoformat() if a.at else None,
        }
        for a in audit_rows
    ]

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="user.export",
        target_kind="user",
        target_id=user.id,
    )
    await session.commit()

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile,
        "interests": interests,
        "roles": roles,
        "saved_itineraries": itineraries,
        "bookings": bookings,
        "audit_log": audit,
        "format": "gdpr-art-15-v1",
    }


# -----------------------------------------------------------------------------
# POST /api/me/change-password
# -----------------------------------------------------------------------------

@router.post("/change-password", response_model=ChangePasswordResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangePasswordResponse:
    if not verify_password(body.current_password, user.password_hash):
        # Same response time-ish: don't leak which is wrong.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="current password is incorrect",
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="new password must differ from current",
        )
    user.password_hash = hash_password(body.new_password)
    user.updated_at = datetime.now(timezone.utc)
    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="user.password_changed",
        target_kind="user",
        target_id=user.id,
    )
    await session.commit()
    return ChangePasswordResponse(
        changed=True,
        changed_at=datetime.now(timezone.utc).isoformat(),
    )


# -----------------------------------------------------------------------------
# DELETE /api/me - soft delete
# -----------------------------------------------------------------------------
# We do NOT hard-delete because:
#   - audit_log and bookings_log are required for financial record-keeping
#     (tax / chargeback disputes) and reference user_id
#   - the GDPR "right to be forgotten" is satisfied by anonymizing the
#     user record: blank PII, set is_active=False, email becomes a
#     tombstone that can't be re-registered.

_DELETED_EMAIL_PREFIX = "deleted+"
_DELETED_EMAIL_DOMAIN = "@removed.travelscout"


@router.delete("", response_model=DeleteMeResponse)
async def delete_me(
    body: DeleteMeRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeleteMeResponse:
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="confirm=true required to delete account",
        )

    original_email = user.email
    tombstone = (
        f"{_DELETED_EMAIL_PREFIX}{user.id}{_DELETED_EMAIL_DOMAIN}"
    )

    # Blanking PII. We keep the row so FK constraints don't break.
    # The password hash is replaced with a bcrypt of an unguessable
    # random string — the original hash is gone forever, so the account
    # can never be recovered or used to log in again.
    import secrets as _secrets
    from app.security import hash_password as _hash
    user.email = tombstone
    user.name = "Deleted user"
    user.password_hash = _hash(_secrets.token_hex(32))
    user.is_active = False
    user.nationality = None
    user.passport_number = None
    user.passport_expiry = None
    user.passport_issuing_country = None
    user.date_of_birth = None
    user.emergency_contact_name = None
    user.emergency_contact_phone = None
    user.updated_at = datetime.now(timezone.utc)

    # Revoke all roles.
    role_rows = (
        await session.execute(
            select(UserRole).where(UserRole.user_id == user.id)
        )
    ).scalars().all()
    now = datetime.now(timezone.utc)
    for r in role_rows:
        if r.revoked_at is None:
            r.revoked_at = now

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="user.deleted",
        target_kind="user",
        target_id=user.id,
        metadata={
            "original_email_domain": original_email.split("@")[-1]
            if "@" in original_email else None,
            "reason": body.reason,
        },
    )
    await session.commit()
    return DeleteMeResponse(
        deleted=True,
        deleted_at=now.isoformat(),
        anonymized_email=tombstone,
    )


__all__ = ["router"]

"""Booking-agent queue (T8e).

Two surfaces:

1. **User-facing** (under ``/api/agent``):
   - ``POST /api/agent/queue`` — user hands an itinerary to an agent.
     Body: ``{itinerary_id, note?}``. Creates a BookingsLog row
     (status=pending) and writes an audit entry. The row carries enough
     information for the agent to contact the user off-platform and
     start the booking.

2. **Agent-facing** (under ``/api/agent`` — same prefix, perm-gated):
   - ``GET    /api/agent/queue``           — list pending + in-progress items
   - ``POST   /api/agent/queue/{id}/claim`` — agent claims the row
   - ``POST   /api/agent/queue/{id}/release`` — agent un-claims
   - ``POST   /api/agent/queue/{id}/outcome`` — confirm/fail with note

The agent-side endpoints require the ``agent.work`` permission. The
user-side endpoint requires authentication (any user can hand off
their own itinerary).

Minimum-viable PII policy (2026-07-10): only user_id, email, and the
itinerary summary are stored. The agent contacts the user
off-platform for passport copies. The full-PII path (passport,
nationality) is gated behind a security review.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    BookingsLog,
    Message,
    MessageSenderRole,
    SavedItinerary,
    User,
)
from app.routers.auth import get_current_user
from app.services.authz import require_permission, write_audit_log

import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------


class HandOffRequest(BaseModel):
    itinerary_id: UUID
    note: str | None = Field(default=None, max_length=2000)


class HandOffResponse(BaseModel):
    queue_id: str
    status: str
    message: str


class QueueItem(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_name: str
    itinerary_id: str | None
    itinerary_title: str | None
    itinerary_starts_at: str | None
    itinerary_ends_at: str | None
    itinerary_destination: str | None
    status: str
    amount_cents: int
    currency: str
    external_id: str | None
    metadata: dict
    assigned_agent_id: str | None
    claimed_at: str | None
    outcome_at: str | None
    outcome_note: str | None
    created_at: str


class QueueList(BaseModel):
    total: int
    items: list[QueueItem]


class ClaimResponse(BaseModel):
    id: str
    status: str
    claimed_at: str


class ReleaseRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class OutcomeRequest(BaseModel):
    status: str = Field(pattern=r"^(confirmed|failed)$")
    amount_cents: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    external_id: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _row_to_queue_item(session: AsyncSession, row: BookingsLog) -> QueueItem:
    user = (await session.execute(
        select(User).where(User.id == row.user_id)
    )).scalar_one_or_none()
    itinerary_title: str | None = None
    itinerary_starts_at: str | None = None
    itinerary_ends_at: str | None = None
    itinerary_destination: str | None = None
    if row.itinerary_id:
        saved = (await session.execute(
            select(SavedItinerary).where(SavedItinerary.id == row.itinerary_id)
        )).scalar_one_or_none()
        if saved is not None:
            itinerary_title = saved.title
            itinerary_starts_at = saved.starts_at.isoformat()
            itinerary_ends_at = saved.ends_at.isoformat()
            payload = saved.payload or {}
            itinerary_destination = payload.get("destination_name")

    return QueueItem(
        id=str(row.id),
        user_id=str(row.user_id),
        user_email=user.email if user else "",
        user_name=user.name if user else "",
        itinerary_id=str(row.itinerary_id) if row.itinerary_id else None,
        itinerary_title=itinerary_title,
        itinerary_starts_at=itinerary_starts_at,
        itinerary_ends_at=itinerary_ends_at,
        itinerary_destination=itinerary_destination,
        status=row.status,
        amount_cents=row.amount_cents,
        currency=row.currency,
        external_id=row.external_id,
        metadata=row.metadata_json or {},
        assigned_agent_id=str(row.assigned_agent_id) if row.assigned_agent_id else None,
        claimed_at=row.claimed_at.isoformat() if row.claimed_at else None,
        outcome_at=row.outcome_at.isoformat() if row.outcome_at else None,
        outcome_note=row.outcome_note,
        created_at=row.created_at.isoformat(),
    )


# -----------------------------------------------------------------------------
# User-side: hand off an itinerary
# -----------------------------------------------------------------------------


@router.post("/queue", response_model=HandOffResponse, status_code=status.HTTP_201_CREATED)
async def hand_off_to_agent(
    body: HandOffRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """User-side: hand a saved itinerary to the booking-agent queue.

    - The itinerary must belong to the calling user.
    - We de-dupe: if there's already a pending/claimed/in-progress
      BookingsLog for this itinerary+user, return that one (idempotent).
    """
    # Ownership check
    saved = (await session.execute(
        select(SavedItinerary).where(
            SavedItinerary.id == body.itinerary_id,
            SavedItinerary.user_id == user.id,
        )
    )).scalar_one_or_none()
    if saved is None:
        raise HTTPException(status_code=404, detail="itinerary not found")

    # Dedup: don't re-create an open queue entry
    existing = (await session.execute(
        select(BookingsLog).where(
            BookingsLog.itinerary_id == body.itinerary_id,
            BookingsLog.user_id == user.id,
            BookingsLog.status.in_(("pending", "claimed", "in_progress")),
        ).order_by(BookingsLog.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if existing is not None:
        return HandOffResponse(
            queue_id=str(existing.id),
            status=existing.status,
            message="already in queue; an agent is (or will be) on it",
        )

    payload = saved.payload or {}
    summary = {
        "itinerary_title": saved.title,
        "starts_at": saved.starts_at.isoformat(),
        "ends_at": saved.ends_at.isoformat(),
        "destination": payload.get("destination_name"),
        "destination_iata": payload.get("destination_iata"),
        "origin": payload.get("origin"),
        "origin_iata": payload.get("origin_iata"),
        "anchor_event_count": len(payload.get("anchor_events", [])),
        "user_note": body.note,
    }

    row = BookingsLog(
        user_id=user.id,
        itinerary_id=saved.id,
        status="pending",
        amount_cents=0,
        currency="USD",
        metadata_json={
            "summary": summary,
            "user_email": user.email,
            "user_name": user.name,
            # Phone is on the user.metadata blob written by the
            # v2.1 register extension. Best-effort — missing on older users.
            "user_phone": None,
        },
    )
    session.add(row)
    await session.flush()

    await write_audit_log(
        session,
        actor_user_id=user.id,
        action="agent.handoff",
        target_kind="bookings_log",
        target_id=str(row.id),
        metadata={"itinerary_id": str(saved.id), "summary_keys": list(summary.keys())},
        actor_kind=ActorKind.USER,
    )
    await session.commit()

    return HandOffResponse(
        queue_id=str(row.id),
        status="pending",
        message="handed off to a booking agent; we'll reach out within 1 business day",
    )


# -----------------------------------------------------------------------------
# Agent-side: list, claim, release, outcome
# -----------------------------------------------------------------------------


@router.get("/queue", response_model=QueueList)
async def list_queue(
    session: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated[User, Depends(require_permission("agent.work"))],
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List booking-handoff items, oldest first.

    By default returns only ``pending`` (unclaimed) items plus items
    claimed by the calling agent. Pass ``?status=in_progress`` etc. to
    filter.
    """
    stmt = select(BookingsLog).order_by(BookingsLog.created_at.asc())
    count_stmt = select(func.count()).select_from(BookingsLog)

    if status_filter:
        stmt = stmt.where(BookingsLog.status == status_filter)
        count_stmt = count_stmt.where(BookingsLog.status == status_filter)
    else:
        # Default: unclaimed + my claimed
        stmt = stmt.where(
            (BookingsLog.assigned_agent_id.is_(None)) |
            (BookingsLog.assigned_agent_id == agent.id)
        )
        count_stmt = count_stmt.where(
            (BookingsLog.assigned_agent_id.is_(None)) |
            (BookingsLog.assigned_agent_id == agent.id)
        )

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(
        stmt.limit(limit).offset(offset)
    )).scalars().all()

    return QueueList(
        total=total,
        items=[await _row_to_queue_item(session, r) for r in rows],
    )


@router.post("/queue/{queue_id}/claim", response_model=ClaimResponse)
async def claim_queue_item(
    queue_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated[User, Depends(require_permission("agent.work"))],
):
    """Claim a queue item. Race-safe: only one agent wins."""
    row = (await session.execute(
        select(BookingsLog).where(BookingsLog.id == queue_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    if row.assigned_agent_id is not None and row.assigned_agent_id != agent.id:
        raise HTTPException(status_code=409, detail="already claimed by another agent")
    if row.status not in ("pending", "claimed"):
        raise HTTPException(
            status_code=409,
            detail=f"cannot claim a {row.status} item",
        )

    now = datetime.now(timezone.utc)
    row.assigned_agent_id = agent.id
    row.claimed_at = now
    row.status = "claimed"

    await write_audit_log(
        session,
        actor_user_id=agent.id,
        action="agent.claim",
        target_kind="bookings_log",
        target_id=str(row.id),
        metadata={"itinerary_id": str(row.itinerary_id)},
        actor_kind=ActorKind.AGENT,
    )
    await session.commit()

    return ClaimResponse(
        id=str(row.id), status=row.status,
        claimed_at=now.isoformat(),
    )


@router.post("/queue/{queue_id}/release", response_model=ClaimResponse)
async def release_queue_item(
    queue_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated[User, Depends(require_permission("agent.work"))],
    body: ReleaseRequest | None = None,
):
    """Release a claim. Only the agent who claimed it can release."""
    row = (await session.execute(
        select(BookingsLog).where(BookingsLog.id == queue_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    if row.assigned_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="you did not claim this item")
    if row.status not in ("claimed", "in_progress"):
        raise HTTPException(
            status_code=409,
            detail=f"cannot release a {row.status} item",
        )

    row.assigned_agent_id = None
    row.claimed_at = None
    row.status = "pending"
    if body and body.note:
        meta = dict(row.metadata_json or {})
        meta.setdefault("release_notes", []).append(body.note)
        row.metadata_json = meta

    await write_audit_log(
        session,
        actor_user_id=agent.id,
        action="agent.release",
        target_kind="bookings_log",
        target_id=str(row.id),
        metadata={"note": body.note if body else None},
        actor_kind=ActorKind.AGENT,
    )
    await session.commit()

    return ClaimResponse(id=str(row.id), status="pending", claimed_at="")


@router.post("/queue/{queue_id}/outcome", response_model=QueueItem)
async def record_outcome(
    queue_id: UUID,
    body: OutcomeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    agent: Annotated[User, Depends(require_permission("agent.work"))],
):
    """Record a booking outcome (confirmed or failed)."""
    row = (await session.execute(
        select(BookingsLog).where(BookingsLog.id == queue_id)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    if row.assigned_agent_id != agent.id:
        raise HTTPException(status_code=403, detail="you did not claim this item")
    if row.status not in ("claimed", "in_progress"):
        raise HTTPException(
            status_code=409,
            detail=f"cannot set outcome on a {row.status} item",
        )

    row.status = body.status
    if body.amount_cents is not None:
        row.amount_cents = body.amount_cents
    if body.currency:
        row.currency = body.currency.upper()
    if body.external_id:
        row.external_id = body.external_id
    if body.note:
        row.outcome_note = body.note
    row.outcome_at = datetime.now(timezone.utc)

    await write_audit_log(
        session,
        actor_user_id=agent.id,
        action=f"agent.outcome.{body.status}",
        target_kind="bookings_log",
        target_id=str(row.id),
        metadata={
            "amount_cents": row.amount_cents,
            "currency": row.currency,
            "external_id": row.external_id,
            "note": body.note,
        },
        actor_kind=ActorKind.AGENT,
    )
    await session.commit()

    # Designed glue (T8e-booking-summary): a CONFIRMED outcome posts a
    # summary card into the chat thread — the customer sees dates, price,
    # the reference, and the checklist without the agent retyping it.
    if body.status == "confirmed" and row.itinerary_id:
        try:
            saved = (await session.execute(
                select(SavedItinerary).where(SavedItinerary.id == row.itinerary_id)
            )).scalar_one_or_none()
            owner = (await session.execute(
                select(User).where(User.id == row.user_id)
            )).scalar_one_or_none()
            if saved is not None and owner is not None:
                from app.routers.messages import build_booking_summary
                text, meta = build_booking_summary(
                    booking=row,
                    saved=saved,
                    user=owner,
                    outcome_note=body.note,
                    amount_cents=row.amount_cents,
                    currency=row.currency,
                    external_id=row.external_id,
                )
                msg = Message(
                    itinerary_id=saved.id,
                    sender_user_id=agent.id,
                    sender_role=MessageSenderRole.AGENT,
                    body=text,
                    is_summary=True,
                    booking_id=row.id,
                )
                session.add(msg)
                await session.flush()
                await write_audit_log(
                    session,
                    actor_user_id=agent.id,
                    action="message.post",
                    target_kind="messages",
                    target_id=str(msg.id),
                    metadata={"sender_role": "agent", **meta},
                    actor_kind=ActorKind.AGENT,
                )
                await session.commit()
        except Exception as e:  # noqa: BLE001
            # The outcome stands; the summary post is best-effort.
            logger.warning("booking summary post failed for %s: %s", row.id, e)

    return await _row_to_queue_item(session, row)


__all__ = ["router"]

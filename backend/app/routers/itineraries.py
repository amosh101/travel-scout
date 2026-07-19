"""T4 — Saved itineraries router.

The user searches, gets ranked itineraries, and saves the ones they want to
keep. The saved itinerary is a snapshot of (a) the search parameters that
produced it, (b) the ranked candidates the system returned, (c) which
candidate they picked, and (d) any anchor events they committed to.

This is the user's history. It's multi-tenant: every itinerary is owned by
exactly one user. Tier guard enforces per-month save limits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    SavedItinerary,
    TierLimit,
    User,
)
from app.routers.auth import get_current_user
from app.services.audit import AuditService
from app.services.tier_guard import TierLimitExceeded, current_period_yyyymm

from sqlalchemy import Integer, cast as sa_cast, func as sa_func

router = APIRouter(prefix="/itineraries", tags=["itineraries"])


# -----------------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------------

class SaveItineraryRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    starts_at: datetime
    ends_at: datetime
    destination_country: str | None = Field(default=None, max_length=64)
    destination_name: str | None = Field(default=None, max_length=200)
    interests: list[str] = Field(default_factory=list)
    anchor_event_ids: list[str] = Field(default_factory=list)
    suggested_event_ids: list[str] = Field(default_factory=list)
    search_params: dict[str, Any] = Field(default_factory=dict)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    notes: str | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    total_price_cents: int | None = None
    # --- v2.1: richer payload so /saved can render the full content ---
    origin: str | None = Field(default=None, max_length=200)
    origin_iata: str | None = Field(default=None, max_length=3)
    destination_iata: str | None = Field(default=None, max_length=3)
    destination_country_alpha2: str | None = Field(default=None, max_length=2)
    anchor_events: list[dict[str, Any]] = Field(default_factory=list)
    suggested_events: list[dict[str, Any]] = Field(default_factory=list)  # T8d
    event_window: dict[str, Any] | None = None  # T8a
    flights: list[dict[str, Any]] = Field(default_factory=list)
    hotels: list[dict[str, Any]] = Field(default_factory=list)
    route: dict[str, Any] | None = None
    why: list[str] = Field(default_factory=list)  # legacy alias; see ``pitch`` below
    pitch: list[str] = Field(default_factory=list)
    score: float | None = None
    sources_used: list[str] = Field(default_factory=list)


class UpdateItineraryRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    anchor_event_ids: list[str] | None = None
    suggested_event_ids: list[str] | None = None


class ItineraryOut(BaseModel):
    id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    destination_country: str | None
    destination_name: str | None
    interests: list[str]
    anchor_event_ids: list[str]
    suggested_event_ids: list[str]
    notes: str | None
    currency: str
    total_price_cents: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# -----------------------------------------------------------------------------
# Tier limit helper
# -----------------------------------------------------------------------------
# Tier limits live in the ``tier_limits`` table (seeded by scripts/seed_reference).
# -1 means "unlimited" (no per-month cap). 0 would mean "feature disabled".

async def _check_save_quota(session: AsyncSession, user: User) -> None:
    tier_row = (
        await session.execute(
            select(TierLimit).where(TierLimit.tier == user.tier)
        )
    ).scalar_one_or_none()
    if tier_row is None:
        # No tier row seeded: fall back to FREE limit so we never silently
        # allow unlimited saves on misconfiguration.
        limit = 3
    else:
        limit = tier_row.max_saved_per_month
    if limit is not None and limit < 0:
        return  # -1 = unlimited
    if limit is None or limit <= 0:
        raise TierLimitExceeded(
            tier=user.tier.value,
            action="save_itinerary",
            current=0,
            limit=0,
        )

    period = current_period_yyyymm()
    # Count saves in current month (YYYYMM as integer).
    stmt = (
        select(sa_func.count())
        .select_from(SavedItinerary)
        .where(
            SavedItinerary.user_id == user.id,
            sa_cast(
                sa_func.to_char(SavedItinerary.created_at, "YYYYMM"),
                Integer,
            )
            == period,
        )
    )
    current = (await session.execute(stmt)).scalar_one()
    if current >= limit:
        raise TierLimitExceeded(
            tier=user.tier.value,
            action="save_itinerary",
            current=current,
            limit=limit,
        )


def _row_to_out(row: SavedItinerary) -> dict[str, Any]:
    payload = row.payload or {}
    return {
        "id": str(row.id),
        "title": row.title,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat(),
        "destination_country": payload.get("destination_country"),
        "destination_name": payload.get("destination_name"),
        "interests": payload.get("interests", []),
        "anchor_event_ids": payload.get("anchor_event_ids", []),
        "suggested_event_ids": payload.get("suggested_event_ids", []),
        "notes": payload.get("notes"),
        "currency": row.currency,
        "total_price_cents": row.total_price_cents,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        # v2.1 rich content
        "origin": payload.get("origin"),
        "origin_iata": payload.get("origin_iata"),
        "destination_iata": payload.get("destination_iata"),
        "destination_country_alpha2": payload.get("destination_country_alpha2"),
        "anchor_events": payload.get("anchor_events", []),
        "suggested_events": payload.get("suggested_events", []),  # T8d
        "event_window": payload.get("event_window"),              # T8a
        "flights": payload.get("flights", []),
        "hotels": payload.get("hotels", []),
        "route": payload.get("route"),
        "why": payload.get("why") or payload.get("pitch") or [],
        "pitch": payload.get("pitch") or payload.get("why") or [],
        "score": payload.get("score"),
        "sources_used": payload.get("sources_used", []),
    }


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.post("", status_code=status.HTTP_201_CREATED)
async def save_itinerary(
    body: SaveItineraryRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    if body.ends_at <= body.starts_at:
        raise HTTPException(400, "ends_at must be after starts_at")
    # T8b: hard 14-day cap on saved itineraries. Anything longer is not a
    # trip-around-an-event and shouldn't be in the bookings log.
    if (body.ends_at - body.starts_at).days > 14:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="itinerary exceeds 14-day cap; please narrow the dates",
        )

    await _check_save_quota(session, user)

    payload = {
        "destination_country": body.destination_country,
        "destination_name": body.destination_name,
        "interests": body.interests,
        "anchor_event_ids": body.anchor_event_ids,
        "suggested_event_ids": body.suggested_event_ids,
        "search_params": body.search_params,
        "candidates": body.candidates,
        "notes": body.notes,
        # v2.1 rich content
        "origin": body.origin,
        "origin_iata": body.origin_iata,
        "destination_iata": body.destination_iata,
        "destination_country_alpha2": body.destination_country_alpha2,
        "anchor_events": body.anchor_events,
        "suggested_events": body.suggested_events,  # T8d
        "event_window": body.event_window,           # T8a
        "flights": body.flights,
        "hotels": body.hotels,
        "route": body.route,
        "why": body.why or body.pitch,  # accept either; new callers send ``pitch``
        "pitch": body.pitch or body.why,
        "score": body.score,
        "sources_used": body.sources_used,
    }

    row = SavedItinerary(
        user_id=user.id,
        title=body.title.strip(),
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        payload=payload,
        currency=body.currency.upper(),
        total_price_cents=body.total_price_cents,
    )
    session.add(row)
    await session.flush()

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="itinerary.save",
        target_kind="saved_itinerary",
        target_id=row.id,
        metadata={
            "title": row.title,
            "interests": body.interests,
            "anchor_count": len(body.anchor_event_ids),
            "suggested_count": len(body.suggested_event_ids),
        },
    )

    await session.commit()
    await session.refresh(row)
    return _row_to_out(row)


@router.get("")
async def list_itineraries(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    stmt = (
        select(SavedItinerary)
        .where(SavedItinerary.user_id == user.id)
        .order_by(SavedItinerary.created_at.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(SavedItinerary)
        .where(SavedItinerary.user_id == user.id)
    )
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(stmt.limit(limit).offset(offset))
    ).scalars().all()
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [_row_to_out(r) for r in rows],
    }


@router.get("/{itinerary_id}")
async def get_itinerary(
    itinerary_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    stmt = select(SavedItinerary).where(
        SavedItinerary.id == itinerary_id,
        SavedItinerary.user_id == user.id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "itinerary not found")
    return _row_to_out(row)


@router.patch("/{itinerary_id}")
async def update_itinerary(
    itinerary_id: UUID,
    body: UpdateItineraryRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    stmt = select(SavedItinerary).where(
        SavedItinerary.id == itinerary_id,
        SavedItinerary.user_id == user.id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "itinerary not found")

    payload = dict(row.payload or {})
    changed: dict[str, Any] = {}
    if body.title is not None:
        row.title = body.title.strip()
        changed["title"] = row.title
    if body.notes is not None:
        payload["notes"] = body.notes
        changed["notes"] = body.notes
    if body.anchor_event_ids is not None:
        payload["anchor_event_ids"] = body.anchor_event_ids
        changed["anchor_event_ids"] = body.anchor_event_ids
    if body.suggested_event_ids is not None:
        payload["suggested_event_ids"] = body.suggested_event_ids
        changed["suggested_event_ids"] = body.suggested_event_ids

    row.payload = payload
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="itinerary.update",
        target_kind="saved_itinerary",
        target_id=row.id,
        metadata=changed,
    )

    await session.commit()
    await session.refresh(row)
    return _row_to_out(row)


@router.delete("/{itinerary_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itinerary(
    itinerary_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    stmt = select(SavedItinerary).where(
        SavedItinerary.id == itinerary_id,
        SavedItinerary.user_id == user.id,
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "itinerary not found")

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="itinerary.delete",
        target_kind="saved_itinerary",
        target_id=row.id,
        metadata={"title": row.title},
    )

    await session.delete(row)
    await session.commit()
    return None

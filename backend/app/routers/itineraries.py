"""
The itineraries router — exposes the product's core endpoint.

POST /api/itineraries/find
    The "Find my next trip" button. Reads the user's interests, runs
    the intersection algorithm against the events catalog, composes a
    day-by-day itinerary for each candidate (attaching a flight), and
    returns ranked results. Persists nothing — the user picks which
    to save.

POST /api/itineraries/{trip_id}/save
    Save one of the /find results as a SavedTrip row so the user can
    retrieve it later, and so future /find runs can detect
    "you saved this last week" via the stable intersection_id.

POST /api/itineraries/{trip_id}/dismiss
    Mark an intersection_id as dismissed. Idempotent. Future /find
    runs exclude it.

GET /api/itineraries
    List the user's saved trips, most recent first.

GET /api/itineraries/{trip_id}
    Retrieve one saved trip by its intersection_id.

Every mutating endpoint writes one row to audit_log via AuditLogger.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Interest, SavedTrip, DismissedTrip, User
from app.routers.auth import get_current_user
from app.services.audit import AuditLogger
from app.services.intersections import find_intersections
from app.services.itinerary_composer import compose_itinerary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/itineraries", tags=["itineraries"])


# ─── Data loaders (the router pulls the catalog from disk on every /find) ──
#
# Why on every call instead of cached:
#   - The catalog is small (51 events, 30 flights = ~32 KB JSON).
#   - Caching would add a Redis dependency for a 1ms read.
#   - On a per-request basis this is honest about freshness — the user
#     always sees the latest fixture data, including any updates from
#     the weekly refresh cron.
#   - When the catalog grows past ~1 MB or /find is called >10x/sec per
#     user, switch to a process-level lru_cache or Redis.

_REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/routers → repo root
_EVENTS_PATH = _REPO_ROOT / "data" / "events.json"
_FLIGHTS_PATH = _REPO_ROOT / "data" / "flights.json"


def _load_events() -> list[dict]:
    """Load the events catalog from data/events.json. Returns [] if missing."""
    if not _EVENTS_PATH.exists():
        logger.warning(f"events.json not found at {_EVENTS_PATH}")
        return []
    with open(_EVENTS_PATH) as f:
        return json.load(f)


def _load_flights() -> list[dict]:
    """Load the flight catalog from data/flights.json. Returns [] if missing."""
    if not _FLIGHTS_PATH.exists():
        logger.warning(f"flights.json not found at {_FLIGHTS_PATH}")
        return []
    with open(_FLIGHTS_PATH) as f:
        return json.load(f)


# ─── Default user origin (where the user is flying from) ──────────────────
#
# v1 assumption: MPM (Maputo). Personal tool, one user, hardcoded.
# MVP-2 makes this a per-user preference on the User model.
DEFAULT_USER_ORIGIN = "MPM"


# ─── /find ────────────────────────────────────────────────────────────────


@router.post("/find")
async def find_itineraries(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run the intersection algorithm and return ranked candidates with
    attached itineraries.

    Body (all optional):
      {
        "user_origin": "MPM",           # override the default origin
        "date_window_days": 7,          # event window (default 7)
        "max_results": 20               # cap on returned candidates
      }
    """
    # Parse the optional body. TestClient sends {} for missing body; we
    # tolerate either {} or no body at all.
    try:
        body = await request.json()
    except Exception:
        body = {}
    user_origin = body.get("user_origin") or DEFAULT_USER_ORIGIN
    date_window_days = int(body.get("date_window_days") or 7)
    max_results = int(body.get("max_results") or 20)

    # 1. Load the user's interests
    result = await db.execute(
        select(Interest)
        .where(Interest.user_id == current_user.id, Interest.active.is_(True))
        .order_by(Interest.priority.asc(), Interest.created_at.asc())
    )
    interests_rows = result.scalars().all()
    if len(interests_rows) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"At least 2 active interests are required to find trips "
                f"(you have {len(interests_rows)}). Add more interests first."
            ),
        )

    # Convert SQLAlchemy rows to the plain-dict shape the algorithm expects.
    interests = [
        {
            "id": str(i.id),
            "name": i.name,
            "event_keywords": i.event_keywords or "",
            "destination_region": i.destination_region,
            "priority": i.priority if i.priority is not None else 5,
        }
        for i in interests_rows
    ]

    # 2. Load dismissed intersection_ids for this user
    dismissed_result = await db.execute(
        select(DismissedTrip.intersection_id).where(
            DismissedTrip.user_id == current_user.id
        )
    )
    dismissed_ids = {row[0] for row in dismissed_result.all()}

    # 3. Load the catalogs
    events = _load_events()
    flights = _load_flights()

    # 4. Find intersections
    candidates = find_intersections(
        interests, events,
        date_window_days=date_window_days,
        dismissed_ids=dismissed_ids,
    )
    candidates = candidates[:max_results]

    # 5. Compose itinerary for each candidate (attaches a flight)
    out = []
    for cand in candidates:
        itinerary = compose_itinerary(
            cand, events, flights, user_origin=user_origin,
        )
        out.append({
            "id": cand.id,
            "city": cand.city,
            "country": cand.country,
            "start_date": cand.start_date.isoformat(),
            "end_date": cand.end_date.isoformat(),
            "events": [
                {
                    "id": m.event.get("id"),
                    "name": m.event.get("name"),
                    "type": m.event.get("type"),
                    "city": m.event.get("city"),
                    "country": m.event.get("country"),
                    "start_date": m.event.get("start_date"),
                    "end_date": m.event.get("end_date"),
                    "matched_keyword": m.matched_keyword,
                    "match_strength": m.match_strength,
                    "source_url": m.event.get("source_url"),
                }
                for m in cand.events
            ],
            "interests": [
                {
                    "id": str(i.get("id")),
                    "name": i.get("name"),
                    "priority": i.get("priority"),
                }
                for i in cand.interests
            ],
            "score": cand.score,
            "score_breakdown": cand.score_breakdown,
            "itinerary": (
                {
                    "id": itinerary.id,
                    "origin": itinerary.origin,
                    "destination_airport": itinerary.destination_airport,
                    "destination_city": itinerary.destination_city,
                    "destination_country": itinerary.destination_country,
                    "depart_date": itinerary.depart_date.isoformat(),
                    "return_date": itinerary.return_date.isoformat(),
                    "flight_price_usd": itinerary.flight_price_usd,
                    "flight_booking_url": itinerary.flight_booking_url,
                    "flight_id": itinerary.flight_id,
                    "days": [
                        {
                            "date": d.date.isoformat(),
                            "events": [
                                {"id": e.get("id"), "name": e.get("name"),
                                 "type": e.get("type"),
                                 "start_date": e.get("start_date"),
                                 "end_date": e.get("end_date")}
                                for e in d.events
                            ],
                            "notes": d.notes,
                        }
                        for d in itinerary.days
                    ],
                    "est_total_cost_usd": itinerary.est_total_cost_usd,
                }
                if itinerary is not None
                else None
            ),
        })

    # 6. Audit the find (even if 0 results — the action is meaningful)
    await AuditLogger(db).record(
        action="itinerary.find",
        user_id=current_user.id,
        target_type="user",
        target_id=str(current_user.id),
        after={"candidate_count": len(out), "user_origin": user_origin},
        ip_address=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()

    return {
        "candidates": out,
        "count": len(out),
        "user_origin": user_origin,
        "date_window_days": date_window_days,
    }


# ─── /save ────────────────────────────────────────────────────────────────


@router.post("/{trip_id}/save", status_code=status.HTTP_201_CREATED)
async def save_itinerary(
    trip_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save a trip (by intersection_id) to the user's SavedTrip list.

    Idempotent: saving the same id twice is a no-op (returns 200, not 409).
    The first save stores the snapshot; subsequent saves leave it alone
    (the user's first save reflects what they actually saw).
    """
    # Check for existing save
    existing = await db.execute(
        select(SavedTrip).where(
            SavedTrip.user_id == current_user.id,
            SavedTrip.intersection_id == trip_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {
            "message": "Already saved",
            "intersection_id": trip_id,
            "idempotent": True,
        }

    # Build a snapshot from the latest /find data. We don't have the
    # candidate payload here — the client must POST the snapshot as the
    # request body. v1 contract: client sends the candidate JSON it
    # received from /find. v2: store candidates server-side in a
    # candidate_cache table so the snapshot can be reconstructed.
    try:
        body = await request.json()
    except Exception:
        body = {}
    snapshot = body.get("snapshot") or {}
    if not snapshot:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Provide a 'snapshot' field with the candidate payload "
                "from /api/itineraries/find. v1 contract: client supplies "
                "the snapshot; v2 will reconstruct server-side."
            ),
        )

    # Parse the candidate's dates from the snapshot (with safe defaults)
    start_str = snapshot.get("start_date")
    end_str = snapshot.get("end_date")
    start_d = _parse_date_or_none(start_str)
    end_d = _parse_date_or_none(end_str)

    saved = SavedTrip(
        user_id=current_user.id,
        intersection_id=trip_id,
        city=snapshot.get("city", "Unknown"),
        country=snapshot.get("country"),
        start_date=start_d,
        end_date=end_d,
        snapshot_json=snapshot,
    )
    db.add(saved)
    await db.flush()

    await AuditLogger(db).record(
        action="trip.save",
        user_id=current_user.id,
        target_type="saved_trip",
        target_id=str(saved.id),
        after={"intersection_id": trip_id, "city": saved.city},
        ip_address=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()

    return {
        "message": "Trip saved",
        "intersection_id": trip_id,
        "saved_id": str(saved.id),
        "idempotent": False,
    }


# ─── /dismiss ─────────────────────────────────────────────────────────────


@router.post("/{trip_id}/dismiss", status_code=status.HTTP_200_OK)
async def dismiss_itinerary(
    trip_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dismiss a trip. Idempotent: re-dismissing is a no-op."""
    existing = await db.execute(
        select(DismissedTrip).where(
            DismissedTrip.user_id == current_user.id,
            DismissedTrip.intersection_id == trip_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return {
            "message": "Already dismissed",
            "intersection_id": trip_id,
            "idempotent": True,
        }

    dismissed = DismissedTrip(
        user_id=current_user.id,
        intersection_id=trip_id,
    )
    db.add(dismissed)
    await db.flush()

    await AuditLogger(db).record(
        action="trip.dismiss",
        user_id=current_user.id,
        target_type="dismissed_trip",
        target_id=str(dismissed.id),
        after={"intersection_id": trip_id},
        ip_address=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )
    await db.commit()

    return {
        "message": "Trip dismissed",
        "intersection_id": trip_id,
        "idempotent": False,
    }


# ─── GET / (list) ─────────────────────────────────────────────────────────


@router.get("")
async def list_itineraries(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List the user's saved trips, most recent first."""
    result = await db.execute(
        select(SavedTrip)
        .where(SavedTrip.user_id == current_user.id)
        .order_by(SavedTrip.saved_utc.desc())
    )
    saved = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "intersection_id": s.intersection_id,
            "city": s.city,
            "country": s.country,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
            "snapshot_json": s.snapshot_json,
            "saved_utc": s.saved_utc.isoformat() if s.saved_utc else None,
        }
        for s in saved
    ]


# ─── GET /{trip_id} ───────────────────────────────────────────────────────


@router.get("/{trip_id}")
async def get_itinerary(
    trip_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve one saved trip by its intersection_id."""
    result = await db.execute(
        select(SavedTrip).where(
            SavedTrip.user_id == current_user.id,
            SavedTrip.intersection_id == trip_id,
        )
    )
    saved = result.scalar_one_or_none()
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No saved trip with id {trip_id!r} for the current user.",
        )
    return {
        "id": str(saved.id),
        "intersection_id": saved.intersection_id,
        "city": saved.city,
        "country": saved.country,
        "start_date": saved.start_date.isoformat() if saved.start_date else None,
        "end_date": saved.end_date.isoformat() if saved.end_date else None,
        "snapshot_json": saved.snapshot_json,
        "saved_utc": saved.saved_utc.isoformat() if saved.saved_utc else None,
    }


# ─── Internals ─────────────────────────────────────────────────────────────


def _parse_date_or_none(value) -> Optional[date]:
    """Parse a date string in ISO format (YYYY-MM-DD). Returns None on failure."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
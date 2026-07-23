"""Profile / intake router — Step 1 of the new user journey.

The landing page asks the user for their origin, optional destination
preferences, interests, and a "when" window. We never ask the user to
register first; we just stash the answers in Redis under a random
``intent_id`` and hand it to the onboarding page, which combines the
intent with the registration form on submit.

Date window semantics: the user picks ``when`` from
``TravelWhen`` (now / month / quarter / year / specific). The intake
handler expands the preset into ``(date_from, date_to)`` and stores
both. Discover then clamps its event scan to that window — we never
surface events outside what the user actually asked for.

A future "upcoming events" tab can scan beyond this window; today the
profile window is the only window.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_session
from app.models import Interest, Subscription, User, UserInterest
from app.models import ActorKind, UserRole
from app.schemas.me import ChangePasswordIn, MeOut, MePatch, OnboardingIn, OnboardingOut
from app.security import hash_password, verify_password
from app.services.authz import get_current_user, write_audit_log
from app.services.redis_intent import delete_intent, load_intent, store_intent
from app.services.travel_when import (
    MAX_LOOKAHEAD_DAYS,
    TravelWhen,
    label as when_label,
    window_for,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

# -----------------------------------------------------------------------------
# Curated interest catalog. The PR lists 17 categories; keep the same
# names so the UI labels match the API.
#
# The ``key`` is a stable slug we use in URLs and storage; the ``name`` is
# what the user sees. ``event_keywords`` is the list passed into the
# intersection algorithm as a hint.
# -----------------------------------------------------------------------------
INTEREST_CATALOG: list[dict[str, Any]] = [
    {"key": "f1", "name": "F1 / motorsport",
     "event_keywords": ["formula 1", "f1", "grand prix", "motorsport"]},
    {"key": "jazz", "name": "Jazz",
     "event_keywords": ["jazz", "montreux", "north sea jazz"]},
    {"key": "electronic-music", "name": "Electronic music",
     "event_keywords": ["electronic", "techno", "house", "edm", "tomorrowland"]},
    {"key": "rock", "name": "Rock",
     "event_keywords": ["rock", "indie rock", "metal"]},
    {"key": "classical", "name": "Classical music",
     "event_keywords": ["classical", "symphony", "philharmonic"]},
    {"key": "art-museums", "name": "Art / museums",
     "event_keywords": ["museum", "exhibition", "art gallery", "uffizi", "louvre"]},
    {"key": "architecture", "name": "Architecture",
     "event_keywords": ["architecture", "bauhaus", "art deco"]},
    {"key": "public-holidays", "name": "Public holidays / cultural events",
     "event_keywords": ["national day", "public holiday", "carnival"]},
    {"key": "cycling", "name": "Cycling",
     "event_keywords": ["tour de france", "giro", "vuelta", "cycling"]},
    {"key": "food-wine", "name": "Food / wine",
     "event_keywords": ["food", "wine", "gastronomy", "michelin"]},
    {"key": "sport", "name": "Sport (football / tennis / NBA)",
     "event_keywords": ["football", "soccer", "tennis", "nba", "premier league"]},
    {"key": "nightlife", "name": "Nightlife",
     "event_keywords": ["nightlife", "club", "bar"]},
    {"key": "design", "name": "Design",
     "event_keywords": ["design", "salone del mobile", "milan design week"]},
    {"key": "literature", "name": "Literature",
     "event_keywords": ["book fair", "literature", "frankfurt book fair"]},
    {"key": "adventure", "name": "Adventure",
     "event_keywords": ["hiking", "safari", "kayak", "adventure"]},
    {"key": "wellness", "name": "Wellness",
     "event_keywords": ["spa", "wellness", "retreat", "thermal"]},
    {"key": "photography", "name": "Photography",
     "event_keywords": ["photography", "photo festival", "rencontres d'arles"]},
]
_INTEREST_KEYS = {entry["key"] for entry in INTEREST_CATALOG}

# Curated destination chips: SADC + Europe + key cities.
DESTINATION_CHIPS: list[str] = [
    # SADC
    "Maputo", "Johannesburg", "Cape Town", "Durban", "Windhoek",
    "Gaborone", "Lilongwe", "Lusaka", "Harare", "Antananarivo",
    "Mauritius", "Dar es Salaam", "Nairobi", "Kigali",
    # Europe
    "Lisbon", "Porto", "Madrid", "Barcelona", "Seville",
    "Paris", "Lyon", "Marseille",
    "London", "Edinburgh",
    "Amsterdam", "Brussels", "Antwerp",
    "Berlin", "Munich", "Hamburg",
    "Zurich", "Geneva", "Vienna", "Salzburg",
    "Rome", "Florence", "Milan", "Venice", "Naples",
    "Athens", "Istanbul",
    "Copenhagen", "Stockholm", "Oslo", "Helsinki",
    "Prague", "Budapest", "Warsaw", "Krakow",
    "Dublin", "Reykjavik",
    # Asia / Americas
    "Tokyo", "Kyoto", "Singapore", "Bangkok", "Bali",
    "Dubai", "Abu Dhabi", "Doha",
    "New York", "Los Angeles", "San Francisco", "Chicago",
    "Mexico City", "Buenos Aires", "Sao Paulo", "Rio de Janeiro",
]


def _validate_interest_keys(keys: list[str]) -> list[str]:
    """Lowercase, dedupe, keep only catalog keys; return validated list.

    Unknown keys are silently dropped (frontend may pass an ``other`` value
    which is kept separately as ``interest_name``).
    """
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        k_norm = k.strip().lower()
        if not k_norm:
            continue
        if k_norm not in _INTEREST_KEYS:
            continue
        if k_norm in seen:
            continue
        seen.add(k_norm)
        out.append(k_norm)
    return out


# -----------------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------------

class IntakeRequest(BaseModel):
    origin: str = Field(default="Maputo", min_length=1, max_length=200)
    destinations: list[str] = Field(default_factory=list, max_length=20)
    interests: list[str] = Field(default_factory=list, max_length=40)
    interest_name: str | None = Field(default=None, max_length=200)  # free-text "other"
    # New: the date-window enum. Defaults to "now" (next 14 days).
    when: TravelWhen = TravelWhen.NOW
    # Used only when ``when == SPECIFIC``; ignored otherwise.
    date_from: date | None = None
    date_to: date | None = None

    class Config:
        # Pydantic v1 backwards-compat: accept legacy payloads that still
        # send ``travel_soon``. We translate it into the new ``when``
        # below in the handler.
        extra = "allow"


class IntakeResponse(BaseModel):
    intent_id: str
    expires_in_seconds: int
    origin: str
    destinations: list[str]
    interests: list[str]
    interest_name: str | None
    when: TravelWhen
    when_label: str  # human label e.g. "next 3 months"
    date_from: date | None
    date_to: date | None
    # Backwards-compat fields (some clients still read them).
    travel_soon: bool
    planning_ahead: bool
    stored_in: str  # "redis" | "memory" — honest about where the data lives


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

# In-memory fallback if Redis is down (dev/test). The intent is gone on
# process restart, but the user gets a clear "not stored" answer rather
# than a 500.
_MEMORY_INTENTS: dict[str, dict[str, Any]] = {}


@router.post(
    "/intake",
    response_model=IntakeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_intake(
    body: IntakeRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IntakeResponse:
    # Validate interests: at least one required (catalog or "other").
    catalog_keys = _validate_interest_keys(body.interests)
    has_other = bool(body.interest_name and body.interest_name.strip())
    if not catalog_keys and not has_other:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one interest is required (catalog key or interest_name)",
        )

    # Sanitize destinations: trim, dedupe, drop empties, cap at 20.
    seen: set[str] = set()
    destinations: list[str] = []
    for d in body.destinations:
        d_norm = re.sub(r"\s+", " ", d.strip())
        if not d_norm:
            continue
        k = d_norm.lower()
        if k in seen:
            continue
        seen.add(k)
        destinations.append(d_norm)
        if len(destinations) >= 20:
            break

    origin_norm = re.sub(r"\s+", " ", body.origin.strip())
    if not origin_norm:
        origin_norm = "Maputo"

    # Resolve origin + destinations through the ReferenceService so we
    # store canonical city names, country codes, and IATA codes alongside
    # the raw text. The resolver handles aliases, IATA codes, and
    # disambiguation (Brussels-BE vs Brussels-US).
    from app.refdata.service import ReferenceService
    ref = ReferenceService(session)

    origin_res = await ref.resolve(origin_norm)
    origin_canonical = (
        origin_res.to_dict()["city"]["name"] if origin_res.matched and origin_res.city
        else origin_norm
    )
    origin_iata = (
        origin_res.airport.iata if origin_res.matched and origin_res.airport else None
    )
    origin_country = (
        origin_res.country.alpha2 if origin_res.matched and origin_res.country else None
    )

    # Re-resolve each destination with optional country bias
    destinations_resolved: list[dict[str, Any]] = []
    for d in destinations:
        res = await ref.resolve(d)
        res_d = res.to_dict()
        destinations_resolved.append({
            "raw": d,
            "matched": res_d["matched"],
            "city_name": res_d["city"]["name"] if res_d["city"] else d,
            "city_id": res_d["city"]["id"] if res_d["city"] else None,
            "country_alpha2": res_d["country"]["alpha2"] if res_d["country"] else None,
            "primary_iata": res_d["airport"]["iata"] if res_d["airport"] else None,
            "match_kind": res_d["match_kind"],
            "confidence": res_d["confidence"],
        })

    # ------------------------------------------------------------------
    # Date-window resolution
    # ------------------------------------------------------------------
    # Translate the new ``when`` enum into (date_from, date_to).
    # SPECIFIC uses the user-supplied dates; presets use the lookup table
    # in app.services.travel_when. Legacy ``travel_soon`` payloads
    # (if the front-end is still on the old form) are mapped to NOW or
    # SPECIFIC here so old clients keep working.
    extra = body.model_extra or {}
    legacy_travel_soon = bool(extra.get("travel_soon", False))
    if "when" in body.model_fields_set:
        when = body.when
    elif legacy_travel_soon:
        # Old client sent travel_soon. If they also sent dates, treat
        # it as SPECIFIC; otherwise it's a 2-week window from today
        # (the closest match to the old "no dates = now" behaviour).
        if body.date_from or body.date_to:
            when = TravelWhen.SPECIFIC
        else:
            when = TravelWhen.NOW
    else:
        when = TravelWhen.NOW

    today = date.today()
    if when == TravelWhen.SPECIFIC:
        # User picked specific dates; validate them.
        if body.date_from is None or body.date_to is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="when=specific requires both date_from and date_to",
            )
        if body.date_from < today:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_from cannot be in the past",
            )
        if body.date_to < body.date_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="date_to must be on or after date_from",
            )
        if (body.date_from - today).days > MAX_LOOKAHEAD_DAYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"date_from must be within {MAX_LOOKAHEAD_DAYS} days from today",
            )
        date_from = body.date_from
        date_to = body.date_to
    else:
        date_from, date_to = window_for(when, today=today)

    # Backwards-compat derived flags. ``travel_soon`` = NOW; everything
    # else is "planning ahead" (i.e. the user gave us a wider window).
    travel_soon_flag = (when == TravelWhen.NOW)
    planning_ahead = not travel_soon_flag

    intent_id = secrets.token_urlsafe(24)
    payload: dict[str, Any] = {
        "origin": origin_norm,
        "origin_canonical": origin_canonical,
        "origin_iata": origin_iata,
        "origin_country": origin_country,
        "destinations": destinations,
        "destinations_resolved": destinations_resolved,
        "interests": catalog_keys,
        "interest_name": (body.interest_name or "").strip() or None,
        "when": when.value,
        "when_label": when_label(when),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        # Backwards-compat fields.
        "travel_soon": travel_soon_flag,
        "planning_ahead": planning_ahead,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    stored = await store_intent(intent_id, payload)
    if not stored:
        # Fall back to in-memory store. Honest about it.
        _MEMORY_INTENTS[intent_id] = payload
        logger.warning("Redis unavailable; intent %s stored in memory only", intent_id)
        stored_in = "memory"
    else:
        stored_in = "redis"

    return IntakeResponse(
        intent_id=intent_id,
        expires_in_seconds=60 * 60,
        origin=origin_canonical,  # canonical, not raw
        destinations=[d["city_name"] for d in destinations_resolved],  # canonical
        interests=catalog_keys,
        interest_name=payload["interest_name"],
        when=when,
        when_label=when_label(when),
        date_from=date_from,
        date_to=date_to,
        travel_soon=travel_soon_flag,
        planning_ahead=planning_ahead,
        stored_in=stored_in,
    )


@router.get("/intake/{intent_id}")
async def get_intake(intent_id: str) -> dict[str, Any]:
    """Read back the intake stored against an intent_id (for debugging)."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", intent_id):
        raise HTTPException(status_code=400, detail="invalid intent_id")
    payload = await load_intent(intent_id)
    if payload is None:
        payload = _MEMORY_INTENTS.get(intent_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="intent not found or expired")
    return payload


@router.delete("/intake/{intent_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def discard_intake(intent_id: str) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", intent_id):
        raise HTTPException(status_code=400, detail="invalid intent_id")
    await delete_intent(intent_id)
    _MEMORY_INTENTS.pop(intent_id, None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# T9: Apply an anonymous intake to an already-authenticated user.
#
# Flow:
#   - Logged-in user fills the landing-page form (which always creates an
#     anonymous intent in Redis, even for returning users).
#   - Instead of pushing them through the registration form, the
#     front-end calls this endpoint. We:
#       1. Resolve the intent's interest keys against the catalog and
#          upsert UserInterest rows for any new ones.
#       2. If the user typed an "other" interest, create a new Interest
#          row with a generated slug and link it.
#       3. Write a ``user.intake_updated`` audit row whose
#          ``metadata_json`` matches the shape ``_load_user_profile_intake``
#          reads, so the next discover call uses the new origin,
#          destinations, and dates.
#       4. Delete the intent (no longer needed).
#   - Returns 204; the front-end then pushes the user to /itineraries.
# -----------------------------------------------------------------------------

@router.post(
    "/intake/{intent_id}/apply",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def apply_intake(
    intent_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_\-]{16,64}", intent_id):
        raise HTTPException(status_code=400, detail="invalid intent_id")

    payload = await load_intent(intent_id) or _MEMORY_INTENTS.get(intent_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="intent not found or expired")

    # 1. Upsert catalog-key interests into UserInterest.
    catalog_keys: list[str] = list(payload.get("interests") or [])
    if catalog_keys:
        existing = (
            await session.execute(
                select(Interest).where(Interest.key.in_(catalog_keys))
            )
        ).scalars().all()
        existing_by_key = {i.key: i for i in existing}
        already_linked = {
            r.interest_id
            for r in (
                await session.execute(
                    select(UserInterest).where(UserInterest.user_id == user.id)
                )
            ).scalars().all()
        }
        for key in catalog_keys:
            meta = existing_by_key.get(key)
            if meta is None or meta.id in already_linked:
                continue
            session.add(UserInterest(user_id=user.id, interest_id=meta.id))

    # 2. Free-form "other" interest → create Interest, link to user.
    other_name = (payload.get("interest_name") or "").strip()
    if other_name:
        # Reuse an existing matching Interest if one exists with the same
        # case-insensitive name (to keep duplicates down).
        slug = re.sub(r"[^a-z0-9]+", "-", other_name.lower()).strip("-")[:64]
        if not slug:
            slug = "custom-" + secrets.token_urlsafe(4)
        existing_other = (
            await session.execute(
                select(Interest).where(Interest.key == slug)
            )
        ).scalar_one_or_none()
        if existing_other is None:
            new_interest = Interest(
                key=slug,
                name=other_name[:128],
                event_keywords=[other_name.lower()],
            )
            session.add(new_interest)
            await session.flush()
            interest_id = new_interest.id
        else:
            interest_id = existing_other.id
        already_linked = {
            r.interest_id
            for r in (
                await session.execute(
                    select(UserInterest).where(UserInterest.user_id == user.id)
                )
            ).scalars().all()
        }
        if interest_id not in already_linked:
            session.add(UserInterest(user_id=user.id, interest_id=interest_id))

    # 3. Write the audit row that discover reads for origin/destinations.
    from app.models import ActorKind  # local to avoid widening the top import
    await write_audit_log(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="user.intake_updated",
        target_kind="user",
        target_id=str(user.id),
        metadata={
            "has_intake": True,
            "intent_id": intent_id,
            "origin": payload.get("origin"),
            "origin_canonical": payload.get("origin_canonical"),
            "origin_iata": payload.get("origin_iata"),
            "origin_country": payload.get("origin_country"),
            "destinations": payload.get("destinations") or [],
            "destinations_resolved": payload.get("destinations_resolved") or [],
            "interests": catalog_keys,
            "interest_name": other_name or None,
            "when": payload.get("when"),
            "when_label": payload.get("when_label"),
            "date_from": payload.get("date_from"),
            "date_to": payload.get("date_to"),
            # Backwards-compat for older readers.
            "travel_soon": bool(payload.get("travel_soon")),
        },
    )

    await session.commit()

    # 4. Consume the intent (no longer needed).
    await delete_intent(intent_id)
    _MEMORY_INTENTS.pop(intent_id, None)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -----------------------------------------------------------------------------
# Static reference data — exposed so the frontend can render chip lists
# from the same source of truth the API validates against.
# -----------------------------------------------------------------------------

@router.get("/interests")
async def list_interests() -> dict[str, Any]:
    return {"items": INTEREST_CATALOG, "count": len(INTEREST_CATALOG)}


@router.get("/destinations")
async def list_destinations() -> dict[str, Any]:
    return {"items": DESTINATION_CHIPS, "count": len(DESTINATION_CHIPS)}


# -----------------------------------------------------------------------------
# GET /me — current user summary
# -----------------------------------------------------------------------------
# Returns the authenticated user's id, email, name, tier, next billing date,
# home airport, onboarding flag, and primary role. The user model does not
# yet carry home_airport / onboarding_complete; we return None / False until a
# migration adds them. Role is derived from the first non-revoked UserRole;
# users with no role assignment default to "user".
# -----------------------------------------------------------------------------


@router.get("/me", response_model=MeOut)
async def get_me(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    # Re-fetch the user with roles eagerly loaded (lazy load would fail
    # after the auth dependency's session is consumed).
    user_id = user.id
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    user_full = (await session.execute(stmt)).scalar_one()

    # Resolve primary role (first non-revoked assignment).
    role_key = "user"
    if user_full.roles:
        for ur in user_full.roles:
            if ur.revoked_at is None and ur.role is not None:
                role_key = ur.role.key
                break

    # Resolve next billing date: most recent subscription's
    # current_period_end. Free users have no subscription rows.
    next_billing: str | None = None
    sub_stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_full.id)
        .order_by(Subscription.current_period_end.desc().nullslast())
        .limit(1)
    )
    sub = (await session.execute(sub_stmt)).scalar_one_or_none()
    if sub is not None and sub.current_period_end is not None:
        next_billing = sub.current_period_end.isoformat()

    return MeOut(
        id=user_full.id,
        email=user_full.email,
        name=user_full.name or None,
        tier=user_full.tier.value if hasattr(user_full.tier, "value") else str(user_full.tier),
        next_billing_date=next_billing,
        home_airport=user_full.home_airport,
        onboarding_complete=bool(user_full.onboarding_complete),
        interests=list(user_full.interests_json or []),
        destinations=list(user_full.destinations_json or []),
        role=role_key,
    )


# -----------------------------------------------------------------------------
# PATCH /me — update current user profile
# -----------------------------------------------------------------------------
# Updates the caller's name, nationality, passport (stored obfuscated on
# ``passport_number``), date of birth, emergency contact, and home airport.
# Email and tier are NOT updatable here. Each successful PATCH writes a
# ``profile_update`` audit row whose ``metadata.fields`` lists the names
# of the fields that were actually applied.
# -----------------------------------------------------------------------------


@router.patch("/me", response_model=MeOut)
async def patch_me(
    patch: MePatch,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MeOut:
    # Re-fetch with roles eagerly loaded (same trick as GET /me).
    user_id = user.id
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    user_full = (await session.execute(stmt)).scalar_one()

    # Map API field names → ORM column attributes. None means "no update".
    updates: dict[str, object] = {}
    if patch.name is not None:
        updates["name"] = patch.name
    if patch.nationality is not None:
        updates["nationality"] = patch.nationality
    if patch.passport is not None:
        # T8f TODO: store obfuscated. The obfuscation helper is not yet
        # wired (T8f follow-up card). For now store the raw value in
        # ``passport_number`` — the PATCH endpoint is gated by JWT and
        # the field is column-encrypted at rest by the DB.
        updates["passport_number"] = patch.passport
    if patch.dob is not None:
        updates["date_of_birth"] = patch.dob
    if patch.emergency_contact_name is not None:
        updates["emergency_contact_name"] = patch.emergency_contact_name
    if patch.emergency_contact_phone is not None:
        updates["emergency_contact_phone"] = patch.emergency_contact_phone
    if patch.home_airport is not None:
        # home_airport is now a real column (migration
        # 0002_user_onboarding_fields). Persist it on the User row.
        updates["home_airport"] = patch.home_airport

    for attr, value in updates.items():
        setattr(user_full, attr, value)

    # Audit the change (even if `updates` is empty — a no-op PATCH is still
    # worth recording for compliance, but we skip the row when nothing
    # changed to keep the audit table clean).
    if updates:
        await write_audit_log(
            session,
            actor_user_id=user_full.id,
            action="profile_update",
            target_kind="user",
            target_id=str(user_full.id),
            metadata={"fields": list(updates.keys())},
            actor_kind=ActorKind.USER,
        )

    await session.commit()

    # Re-fetch with roles eagerly loaded (commit() expires relationships,
    # so the user_full instance's .roles would lazy-load outside the
    # async context and blow up with MissingGreenlet).
    stmt2 = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    user_full = (await session.execute(stmt2)).scalar_one()

    # Re-resolve role + next_billing for the response (same as GET /me).
    role_key = "user"
    if user_full.roles:
        for ur in user_full.roles:
            if ur.revoked_at is None and ur.role is not None:
                role_key = ur.role.key
                break

    next_billing: str | None = None
    sub_stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_full.id)
        .order_by(Subscription.current_period_end.desc().nullslast())
        .limit(1)
    )
    sub = (await session.execute(sub_stmt)).scalar_one_or_none()
    if sub is not None and sub.current_period_end is not None:
        next_billing = sub.current_period_end.isoformat()

    return MeOut(
        id=user_full.id,
        email=user_full.email,
        name=user_full.name or None,
        tier=user_full.tier.value if hasattr(user_full.tier, "value") else str(user_full.tier),
        next_billing_date=next_billing,
        home_airport=user_full.home_airport,
        onboarding_complete=bool(user_full.onboarding_complete),
        interests=list(user_full.interests_json or []),
        destinations=list(user_full.destinations_json or []),
        role=role_key,
    )


# -----------------------------------------------------------------------------
# POST /me/onboarding — 3-step wizard store
# -----------------------------------------------------------------------------
# Stores the wizard output (home airport, interest keys, destination
# wishlist) on the current user. ``skippable=True`` records the
# "skipped" audit action and leaves ``onboarding_complete=False`` (so
# the UI can prompt again next login). A real persist is now in place
# via the columns added in migration 0002_user_onboarding_fields.
# -----------------------------------------------------------------------------


@router.post("/me/onboarding", response_model=OnboardingOut)
async def post_me_onboarding(
    payload: OnboardingIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OnboardingOut:
    """Store the 3-step onboarding wizard result.

    Idempotent: a second call with the same body returns 200 with the
    same response shape and writes a second audit row (so the operator
    can see the user re-saved their preferences, which is what they
    asked for).
    """
    # Re-fetch with roles eagerly loaded (same trick as GET /me, so
    # ``.roles`` access below doesn't trigger a lazy load after commit).
    user_id = user.id
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    user_full = (await session.execute(stmt)).scalar_one()

    # ---- Persist the wizard output on the User row --------------------
    # Migration 0002_user_onboarding_fields adds the four columns this
    # writes to. We always overwrite with the latest payload: the wizard
    # is meant to be re-runnable (e.g. the user updates their home
    # airport a week later), and the audit row records each save.
    user_full.home_airport = payload.home_airport
    user_full.interests_json = list(payload.interests)
    user_full.destinations_json = list(payload.destinations)
    # ``skippable=True`` means the user chose to defer; do NOT mark them
    # complete so the UI can prompt them again next login.
    user_full.onboarding_complete = not payload.skippable

    # ---- Audit log ---------------------------------------------------
    audit_action = "onboarding_skipped" if payload.skippable else "onboarding_completed"
    await write_audit_log(
        session,
        actor_user_id=user_full.id,
        action=audit_action,
        target_kind="user",
        target_id=str(user_full.id),
        metadata={
            "home_airport": payload.home_airport,
            "interests": list(payload.interests),
            "destinations": list(payload.destinations),
            "skippable": payload.skippable,
        },
        actor_kind=ActorKind.USER,
    )

    await session.commit()

    # Re-fetch after commit (commit() expires relationships).
    stmt2 = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    user_full = (await session.execute(stmt2)).scalar_one()

    # Re-resolve role (same as GET /me / PATCH /me).
    role_key = "user"
    if user_full.roles:
        for ur in user_full.roles:
            if ur.revoked_at is None and ur.role is not None:
                role_key = ur.role.key
                break

    return OnboardingOut(
        id=user_full.id,
        email=user_full.email,
        name=user_full.name or None,
        tier=user_full.tier.value if hasattr(user_full.tier, "value") else str(user_full.tier),
        next_billing_date=None,
        home_airport=user_full.home_airport,
        onboarding_complete=bool(user_full.onboarding_complete),
        interests=list(user_full.interests_json or []),
        destinations=list(user_full.destinations_json or []),
        role=role_key,
    )


# -----------------------------------------------------------------------------
# POST /me/change-password — user-driven password rotation
# -----------------------------------------------------------------------------
# T3 follow-up: the user can rotate their own password from the profile
# page. The auth dependency (get_current_user) returns 401 if no JWT;
# Pydantic returns 422 if the new password is too short; we return 400
# on a wrong old password (opaque on purpose — we don't leak whether the
# auth was bad or the old password was wrong). On success we re-hash with
# bcrypt and write an audit row, then return 204 with no body.
@router.post(
    "/me/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def change_my_password(
    body: ChangePasswordIn,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    # Re-fetch with roles preloaded, same pattern as the other /me handlers.
    user_id = user.id
    stmt = (
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(UserRole.role))
    )
    user_full = (await session.execute(stmt)).scalar_one()

    # 400 on wrong old password — opaque to avoid leaking which field was wrong.
    if not verify_password(body.old_password, user_full.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="old password does not match",
        )

    # Re-hash the new password with the same bcrypt settings as registration.
    user_full.password_hash = hash_password(body.new_password)

    # Audit row. Action is fixed; metadata records the rotation for security review.
    await write_audit_log(
        session,
        actor_user_id=user_full.id,
        action="password_changed",
        target_kind="user",
        target_id=str(user_full.id),
        metadata={},
        actor_kind=ActorKind.USER,
    )

    await session.commit()
    # 204 No Content — return an empty Response so FastAPI doesn't try to
    # serialize anything.
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = [
    "router",
    "INTEREST_CATALOG",
    "DESTINATION_CHIPS",
    "IntakeRequest",
    "IntakeResponse",
    "MeOut",
    "MePatch",
    "OnboardingIn",
    "OnboardingOut",
    "ChangePasswordIn",
]

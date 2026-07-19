"""Auth router: register, login, me. + get_current_user dependency.

Real implementation. Issues JWTs via app.security.
T4 prerequisite: the itineraries router needs this.

The register endpoint is extended in v2.1 to accept an optional
``intake_id`` (Redis key from POST /api/profile/intake) and an optional
``profile`` block (the rest of the registration form fields: phone,
address, password min length 12, referrer). On success, the backend:

  1. Creates the user (bcrypt password, email unique).
  2. Loads the intake from Redis.
  3. Creates one ``UserInterest`` row per picked catalog interest
     (weight=1.0; priority=MEDIUM), and—if ``interest_name`` is set—
     creates an "other" interest on the fly with that name.
  4. Records the profile_answers JSON in the user record (we extend
     User with a ``profile_answers`` JSONB column at migration time).
  5. Audit row for ``user.register`` (existing behaviour).
  6. Invalidates the intake (one-time use).
  7. Returns the JWT, same as the legacy register.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    Interest,
    InterestPriority,
    User,
    UserInterest,
)
from app.security import (
    create_access_token,
    decode_access_token,
    deobfuscate_passport,
    hash_password,
    obfuscate_passport,
    verify_password,
)
from app.services.audit import AuditService
from app.services.redis_intent import delete_intent, load_intent

logger = logging.getLogger(__name__)

# get_user_permissions is imported lazily inside the /me handler to avoid
# the circular import: app.routers.auth -> app.services.authz -> app.routers.auth.

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PW_LEN = 12


# -----------------------------------------------------------------------------
# Pydantic schemas
# -----------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=_MIN_PW_LEN)
    name: str = ""

    # --- v2.1 extensions (all optional for backward compatibility) ---
    intake_id: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=255)
    referrer: str | None = Field(default=None, max_length=200)

    # --- T8f: international-travel document fields (all optional) ---
    # Nationality and passport-issuing country are ISO 3166-1 alpha-2.
    # Passport number is stored obfuscated; expires and DOB are real dates.
    nationality: str | None = Field(default=None, min_length=2, max_length=2)
    passport_number: str | None = Field(default=None, max_length=64)
    passport_expiry: date | None = None
    passport_issuing_country: str | None = Field(default=None, min_length=2, max_length=2)
    date_of_birth: date | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=255)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _validate_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid email",
        )
    return email


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or malformed Authorization header",
        )
    return authorization.split(" ", 1)[1].strip()


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the current user from a Bearer token. Raises 401 if missing/invalid."""
    token = _bearer(authorization)
    try:
        claims = decode_access_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        ) from e
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token missing sub claim",
        )
    stmt = select(User).where(User.email == sub)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found or inactive"
        )
    return user


async def get_current_user_id(
    user: Annotated[User, Depends(get_current_user)],
) -> UUID:
    return user.id


# -----------------------------------------------------------------------------
# Internal: write user interests from an intake payload
# -----------------------------------------------------------------------------

async def _attach_intake_to_user(
    session: AsyncSession,
    user: User,
    intake: dict[str, Any],
) -> list[UUID]:
    """Create UserInterest rows for each picked interest.

    Returns the list of new UserInterest IDs.

    The interest catalog is seeded (or auto-created for "other" free-text).
    """
    interests: list[str] = list(intake.get("interests") or [])
    interest_name: str | None = (intake.get("interest_name") or "").strip() or None

    if not interests and not interest_name:
        return []

    # Build a key -> Interest map; create Interest rows for any missing
    # catalog keys (defensive: the seed should have created them, but we
    # don't want a missing seed to block registration).
    keys_to_fetch: set[str] = set(interests)
    if interest_name:
        # Free-text "other" gets a stable slug.
        slug = "other-" + re.sub(r"[^a-z0-9]+", "-", interest_name.lower()).strip("-")[:40]
        keys_to_fetch.add(slug)

    if keys_to_fetch:
        existing = (
            await session.execute(
                select(Interest).where(Interest.key.in_(keys_to_fetch))
            )
        ).scalars().all()
    else:
        existing = []
    by_key: dict[str, Interest] = {i.key: i for i in existing}

    # Auto-create missing interest rows so the user's selection persists
    # even if the seed hasn't been re-run with the new catalog.
    from app.routers.profile import INTEREST_CATALOG
    name_by_key: dict[str, str] = {entry["key"]: entry["name"] for entry in INTEREST_CATALOG}
    for key in list(keys_to_fetch):
        if key in by_key:
            continue
        # For the "other-..." slug, the displayed name is the free text.
        if key.startswith("other-"):
            display_name = interest_name or key
        else:
            display_name = name_by_key.get(key, key)
        interest = Interest(
            key=key,
            name=display_name,
            description="",
            event_keywords=[],
        )
        session.add(interest)
        await session.flush()
        by_key[key] = interest

    created_ids: list[UUID] = []
    for key in interests:
        interest = by_key.get(key)
        if interest is None:
            continue
        # Idempotent: skip if the link already exists.
        link_exists = (
            await session.execute(
                select(UserInterest).where(
                    UserInterest.user_id == user.id,
                    UserInterest.interest_id == interest.id,
                )
            )
        ).scalar_one_or_none()
        if link_exists is not None:
            created_ids.append(link_exists.id)
            continue
        link = UserInterest(
            user_id=user.id,
            interest_id=interest.id,
            priority=InterestPriority.MEDIUM,
            destination_flexibility=None,
            notes="from landing-page intake",
        )
        session.add(link)
        await session.flush()
        created_ids.append(link.id)

    if interest_name:
        slug = "other-" + re.sub(r"[^a-z0-9]+", "-", interest_name.lower()).strip("-")[:40]
        interest = by_key.get(slug)
        if interest is not None:
            link_exists = (
                await session.execute(
                    select(UserInterest).where(
                        UserInterest.user_id == user.id,
                        UserInterest.interest_id == interest.id,
                    )
                )
            ).scalar_one_or_none()
            if link_exists is None:
                link = UserInterest(
                    user_id=user.id,
                    interest_id=interest.id,
                    priority=InterestPriority.LOW,
                    notes=f"free-text: {interest_name}",
                )
                session.add(link)
                await session.flush()
                created_ids.append(link.id)

    return created_ids


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    email = _validate_email(body.email)
    if len(body.password) < _MIN_PW_LEN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"password must be at least {_MIN_PW_LEN} characters",
        )

    stmt = select(User).where(User.email == email)
    if (await session.execute(stmt)).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        )

    # Load the intake up front so we can fail loudly if it's missing.
    intake: dict[str, Any] | None = None
    if body.intake_id:
        intake = await load_intent(body.intake_id)
        if intake is None:
            # Not a 500: the user simply took too long, or the link was
            # bookmarked. The frontend will show "your session expired,
            # please start over".
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="intake expired or not found; please restart from the landing page",
            )

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name.strip() or email.split("@")[0],
        is_active=True,
        # T8f: travel-doc fields. All optional; the front-end can
        # add them later via a profile-update endpoint. Passport
        # number is obfuscated at write so a DB dump doesn't leak
        # plaintext PII.
        nationality=body.nationality.upper() if body.nationality else None,
        passport_number=obfuscate_passport(body.passport_number) if body.passport_number else None,
        passport_expiry=body.passport_expiry,
        passport_issuing_country=body.passport_issuing_country.upper() if body.passport_issuing_country else None,
        date_of_birth=body.date_of_birth,
        emergency_contact_name=body.emergency_contact_name,
        emergency_contact_phone=body.emergency_contact_phone,
    )
    session.add(user)
    await session.flush()

    interest_count = 0
    if intake is not None:
        try:
            ids = await _attach_intake_to_user(session, user, intake)
            interest_count = len(ids)
        except Exception as e:  # noqa: BLE001
            # Don't lose the user if interest linking fails; log it.
            logger.exception("Failed to attach intake interests: %s", e)

    # Audit
    metadata: dict[str, Any] = {
        "email": email,
        "has_intake": intake is not None,
        "interests_attached": interest_count,
    }
    if body.phone:
        metadata["phone_provided"] = True
    if body.address:
        metadata["address_provided"] = True
    if body.referrer:
        metadata["referrer"] = body.referrer
    if intake is not None:
        metadata["origin"] = intake.get("origin")
        metadata["destinations"] = intake.get("destinations")
        metadata["when"] = intake.get("when")
        metadata["when_label"] = intake.get("when_label")
        metadata["date_from"] = intake.get("date_from")
        metadata["date_to"] = intake.get("date_to")
        metadata["travel_soon"] = intake.get("travel_soon")

    await AuditService.record(
        session,
        actor_user_id=user.id,
        actor_kind=ActorKind.USER,
        action="user.register",
        target_kind="user",
        target_id=user.id,
        metadata=metadata,
    )

    await session.commit()
    await session.refresh(user)

    # Consume the intent — it's a one-shot.
    if body.intake_id:
        await delete_intent(body.intake_id)

    token = create_access_token(subject=email)
    return TokenResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "tier": user.tier.value,
        },
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    email = _validate_email(body.email)
    stmt = select(User).where(User.email == email)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        # Don't reveal which one failed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="account disabled"
        )
    token = create_access_token(subject=email)
    return TokenResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "name": user.name,
            "tier": user.tier.value,
        },
    )


@router.get("/me")
async def me(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    # Lazy import to break the auth <-> authz circular dependency.
    from app.services.authz import get_user_permissions

    # List the user's stored interests for transparency.
    interest_rows = (
        await session.execute(
            select(UserInterest).where(UserInterest.user_id == user.id)
        )
    ).scalars().all()
    interests_out: list[dict[str, Any]] = []
    if interest_rows:
        ids = [r.interest_id for r in interest_rows]
        interest_meta = (
            await session.execute(select(Interest).where(Interest.id.in_(ids)))
        ).scalars().all()
        meta_by_id = {i.id: i for i in interest_meta}
        for r in interest_rows:
            meta = meta_by_id.get(r.interest_id)
            interests_out.append({
                "key": meta.key if meta else None,
                "name": meta.name if meta else None,
                "priority": r.priority.value,
            })

    perms = await get_user_permissions(session, user.id)
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "tier": user.tier.value,
        "permissions": sorted(perms),
        "interests": interests_out,
    }


__all__ = [
    "router",
    "get_current_user",
    "get_current_user_id",
    "RegisterRequest",
    "TokenResponse",
]

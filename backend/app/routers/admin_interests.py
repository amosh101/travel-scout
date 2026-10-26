"""Admin CRUD for the interest taxonomy (2026-10-21).

The python ``INTEREST_CATALOG`` stays the seed source of truth and the
seed keeps inserting any missing rows (idempotent, on boot). The DB is
the runtime source: admins rename, re-kind, and DEACTIVATE keys here;
deactivation hides a key from onboarding + discover without touching
historical ``user_interests`` rows. Deletes are not offered (an
interest in use can never be hard-deleted safely).

Honest coverage note: an admin-created key has no dedicated source
registration, so discover will return an honest empty for it until an
engineering pass wires sources for it (the seed + probe discipline).
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ActorKind, Interest, User, UserInterest
from app.services.authz import (
    get_current_user,
    require_permission,
    write_audit_log,
)

router = APIRouter(prefix="/admin/interests", tags=["admin-taxonomy"])


class InterestIn(BaseModel):
    key: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=128)
    kind: str | None = Field(default=None, max_length=32)


class InterestPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    kind: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None


@router.get("")
async def list_interests(
    include_inactive: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_permission("destination.admin")),
) -> dict:
    rows = (await session.execute(select(Interest).order_by(Interest.kind, Interest.key))).scalars().all()
    usage = (await session.execute(
        select(UserInterest.interest_id, func.count())
        .group_by(UserInterest.interest_id)
    )).all()
    counts = {str(iid): int(n) for iid, n in usage}
    items = []
    for r in rows:
        if not include_inactive and not r.is_active:
            continue
        items.append(
            {
                "key": r.key,
                "name": r.name,
                "kind": r.kind,
                "is_active": r.is_active,
                "users_with_interest": counts.get(str(r.id), 0),
            }
        )
    return {"total": len(items), "items": items}


@router.post("", status_code=201)
async def create_interest(
    body: InterestIn,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_permission("destination.admin")),
) -> dict:
    existing = (await session.execute(
        select(Interest).where(Interest.key == body.key)
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"interest key {body.key!r} already exists")
    row = Interest(key=body.key, name=body.name, kind=body.kind, is_active=True)
    session.add(row)
    await session.flush()
    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="interest.create",
        target_kind="interests",
        target_id=row.key,
        metadata={"name": body.name, "kind": body.kind},
        actor_kind=ActorKind.ADMIN,
    )
    await session.commit()
    return {"key": row.key, "name": row.name, "kind": row.kind, "is_active": row.is_active,
            "note": "no dedicated event source yet — discover will return an honest-empty "
            "for this key until sources are wired"}


@router.patch("/{key}")
async def patch_interest(
    key: str,
    body: InterestPatch,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_permission("destination.admin")),
) -> dict:
    row = (await session.execute(
        select(Interest).where(Interest.key == key)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"interest key {key!r} not found")

    changes: dict[str, dict[str, Any]] = {}
    if body.name is not None and body.name != row.name:
        changes["name"] = {"from": row.name, "to": body.name}
        row.name = body.name
    if body.kind is not None and body.kind != row.kind:
        changes["kind"] = {"from": row.kind, "to": body.kind}
        row.kind = body.kind
    if body.is_active is not None and body.is_active != row.is_active:
        changes["is_active"] = {"from": row.is_active, "to": body.is_active}
        row.is_active = body.is_active
    if not changes:
        return {"key": row.key, "changed": False}

    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="interest.update",
        target_kind="interests",
        target_id=row.key,
        metadata={"changes": changes},
        actor_kind=ActorKind.ADMIN,
    )
    await session.commit()
    return {"key": row.key, "changed": True, "changes": changes}
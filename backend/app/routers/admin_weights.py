"""Admin endpoint for the intersection-algorithm weights.

The AlgoWeight table has per-key scalar rows (e.g. ``w_interest_match=0.5``,
``w_date_anchor=0.3``). Admins GET the full set and PATCH one row at a time.

Every change appends an audit-log entry with the diff.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ActorKind, AlgoWeight, User
from app.services.authz import require_permission, write_audit_log

router = APIRouter(prefix="/admin/weights", tags=["admin"])


class WeightRow(BaseModel):
    key: str
    value: str
    description: str
    updated_at: str
    updated_by: str | None


class WeightsList(BaseModel):
    items: list[WeightRow]


class UpdateWeightRequest(BaseModel):
    value: str = Field(min_length=1, max_length=255)
    description: str | None = None


@router.get("", response_model=WeightsList)
async def list_weights(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_permission("weights.update"))],
):
    rows = (await session.execute(
        select(AlgoWeight).order_by(AlgoWeight.key)
    )).scalars().all()
    return WeightsList(items=[
        WeightRow(
            key=r.key,
            value=r.value,
            description=r.description,
            updated_at=r.updated_at.isoformat(),
            updated_by=str(r.updated_by) if r.updated_by else None,
        )
        for r in rows
    ])


@router.patch("/{key}", response_model=WeightRow)
async def update_weight(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("weights.update"))],
    key: str,
    body: UpdateWeightRequest,
):
    row = (await session.execute(
        select(AlgoWeight).where(AlgoWeight.key == key)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"weight key not found: {key}")

    diff: dict = {"value": {"from": row.value, "to": body.value}}
    if body.description is not None and body.description != row.description:
        diff["description"] = {"from": row.description, "to": body.description}
        row.description = body.description
    row.value = body.value
    row.updated_by = admin.id

    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="weights.update",
        target_kind="algo_weight",
        target_id=key,
        metadata={"diff": diff},
        actor_kind=ActorKind.ADMIN,
    )
    await session.commit()

    return WeightRow(
        key=row.key,
        value=row.value,
        description=row.description,
        updated_at=row.updated_at.isoformat(),
        updated_by=str(row.updated_by) if row.updated_by else None,
    )

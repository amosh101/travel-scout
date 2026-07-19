"""Admin endpoint for event + flight sources.

Lists event_sources and flight_sources, lets admins toggle ``enabled``
on each. Audit-logs every change.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ActorKind, EventSource, FlightSource, User
from app.services.authz import require_permission, write_audit_log

router = APIRouter(prefix="/admin/sources", tags=["admin"])


class SourceRow(BaseModel):
    kind: Literal["event", "flight"]
    key: str
    name: str
    base_url: str
    auth_env_var: str | None
    enabled: bool


class SourcesList(BaseModel):
    items: list[SourceRow]


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("", response_model=SourcesList)
async def list_sources(
    session: Annotated[AsyncSession, Depends(get_session)],
    _admin: Annotated[User, Depends(require_permission("source.admin"))],
):
    events = (await session.execute(select(EventSource).order_by(EventSource.key))).scalars().all()
    flights = (await session.execute(select(FlightSource).order_by(FlightSource.key))).scalars().all()

    items: list[SourceRow] = []
    for e in events:
        items.append(SourceRow(
            kind="event", key=e.key, name=e.name,
            base_url=e.base_url, auth_env_var=e.auth_env_var,
            enabled=bool(getattr(e, "enabled", True)),
        ))
    for f in flights:
        items.append(SourceRow(
            kind="flight", key=f.key, name=f.name,
            base_url=f.base_url, auth_env_var=f.auth_env_var,
            enabled=bool(getattr(f, "enabled", True)),
        ))
    return SourcesList(items=items)


@router.patch("/{kind}/{key}", response_model=SourceRow)
async def toggle_source(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("source.admin"))],
    kind: Literal["event", "flight"],
    key: str,
    body: ToggleRequest,
):
    model = EventSource if kind == "event" else FlightSource
    row = (await session.execute(
        select(model).where(model.key == key)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind} source not found: {key}")

    # The model may or may not have an `enabled` column; add gracefully.
    if not hasattr(row, "enabled"):
        raise HTTPException(
            status_code=501,
            detail=f"{kind}_sources table has no 'enabled' column — migration needed",
        )

    old = bool(row.enabled)
    row.enabled = body.enabled
    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="source.toggle",
        target_kind=f"{kind}_source",
        target_id=key,
        metadata={"from": old, "to": body.enabled},
        actor_kind=ActorKind.ADMIN,
    )
    await session.commit()

    return SourceRow(
        kind=kind, key=row.key, name=row.name,
        base_url=row.base_url, auth_env_var=row.auth_env_var,
        enabled=bool(row.enabled),
    )

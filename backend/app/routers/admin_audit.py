"""Admin audit log endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import ActorKind, AuditLog, User
from app.services.authz import require_permission

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit")
async def list_audit_entries(
    session: Annotated[AsyncSession, Depends(get_session)],
    _user: Annotated[User, Depends(require_permission("audit.read"))],
    actor_user_id: UUID | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """Return audit-log entries, newest first.

    Filters: actor_user_id, action (exact), since, until, pagination.
    """
    stmt = select(AuditLog).order_by(AuditLog.at.desc())
    count_stmt = select(func.count()).select_from(AuditLog)

    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        count_stmt = count_stmt.where(AuditLog.actor_user_id == actor_user_id)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    if since is not None:
        stmt = stmt.where(AuditLog.at >= since)
        count_stmt = count_stmt.where(AuditLog.at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.at < until)
        count_stmt = count_stmt.where(AuditLog.at < until)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": str(row.id),
                "actor_user_id": str(row.actor_user_id) if row.actor_user_id else None,
                "actor_kind": row.actor_kind.value,
                "action": row.action,
                "target_kind": row.target_kind,
                "target_id": row.target_id,
                "metadata": row.metadata_json,
                "request_id": row.request_id,
                "at": row.at.isoformat(),
            }
            for row in rows
        ],
    }
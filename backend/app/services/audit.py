"""Audit service: record every privileged action."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActorKind, AuditLog


class AuditService:
    """Append-only audit recorder.

    Routers call ``AuditService.record(...)`` after every privileged mutation.
    The ``request_id`` is attached by ``RequestIdMiddleware`` and resolved here
    via contextvars (see ``app.middleware.request_id``).
    """

    @staticmethod
    async def record(
        session: AsyncSession,
        *,
        actor_user_id: UUID | None,
        actor_kind: ActorKind,
        action: str,
        target_kind: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        from app.middleware.request_id import current_request_id

        row = AuditLog(
            actor_user_id=actor_user_id,
            actor_kind=actor_kind,
            action=action,
            target_kind=target_kind,
            target_id=str(target_id) if target_id is not None else None,
            metadata_json=metadata or {},
            request_id=request_id or current_request_id(),
        )
        session.add(row)
        await session.flush()
        return row


__all__ = ["AuditService"]
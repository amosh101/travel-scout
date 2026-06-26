"""
AuditLogger service — writes to and queries the audit_log table.

Used by every mutating endpoint and by background jobs to record who did
what, when, from where. Append-only.

Design notes:
  - `record()` flushes but does NOT commit, so it slots cleanly inside the
    caller's transaction. The caller controls commit boundaries (the typical
    pattern is: do mutating work + audit.record(...) + commit, all atomic).
  - `query()` is read-only and uses standard SELECT ... ORDER BY ... LIMIT.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


class AuditLogger:
    """Thin service layer over the audit_log table."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        action: str,
        *,
        user_id: UUID | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        source: str = "api",
        ip_address: str | None = None,
        request_id: str | None = None,
    ) -> AuditLog:
        """Write one audit_log row. Returns the persisted AuditLog object.

        Action is required. Other fields optional. Defaults source='api'.
        Flushes but does NOT commit — the caller controls the transaction.
        """
        entry = AuditLog(
            action=action,
            user_id=user_id,
            target_type=target_type,
            target_id=target_id,
            before_json=before,
            after_json=after,
            source=source,
            ip_address=ip_address,
            request_id=request_id,
        )
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def query(
        self,
        *,
        user_id: UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditLog]:
        """Return audit rows filtered by (optional) user_id, action, since.

        Ordered by occurred_utc DESC. Capped at `limit` rows.
        """
        stmt = select(AuditLog)

        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action is not None:
            stmt = stmt.where(AuditLog.action == action)
        if since is not None:
            stmt = stmt.where(AuditLog.occurred_utc >= since)

        stmt = stmt.order_by(AuditLog.occurred_utc.desc()).limit(limit)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())
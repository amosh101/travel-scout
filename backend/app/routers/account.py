"""
GDPR account router — right-to-erasure, data portability, and audit history.

Endpoints (all under /api/account):
  POST /delete  — GDPR Article 17 (right to erasure). Soft-deletes the user
                  (sets is_active=False, clears PII, preserves password_hash
                  so the email can't be re-registered). Writes one
                  audit_log row with action='account.delete'.
  POST /export  — GDPR Article 20 (data portability). Returns the full
                  user-data dump from UserRepository.export_account_data().
                  Writes one audit_log row with action='account.export'.
  GET  /audit   — Returns the current user's audit_log rows, most recent first.
                  Hard-capped at 200 rows.

All endpoints require authentication via the same get_current_user dependency
as the auth router — see app/routers/auth.py.

Design notes:
  - We use the same get_current_user from app.routers.auth (not a re-declared
    copy) so tests can override it via app.dependency_overrides[get_current_user].
  - All audit writes go through AuditLogger so the row shape stays consistent
    with the rest of the app.
  - The router does its own db.commit() because the service layer
    (UserRepository.soft_delete_account, AuditLogger.record) intentionally
    flush-but-don't-commit to keep the transaction boundary at the route.
  - deleted_utc is the timestamp of the soft-delete, not the row's created_at.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user
from app.services.audit import AuditLogger
from app.services.user_repo import UserRepository


router = APIRouter(prefix="/api/account", tags=["account"])


@router.post("/delete", status_code=status.HTTP_200_OK)
async def delete_account(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR right to erasure.

    Soft-deletes the account (sets is_active=False, clears PII, preserves
    password hash so the email cannot be re-registered). Writes one
    audit_log row with action='account.delete'.

    Returns:
        {"message": "Account deleted", "deleted_utc": iso8601_string}
    """
    repo = UserRepository(db)
    await repo.soft_delete_account(current_user.id)

    deleted_utc = datetime.now(timezone.utc)

    await AuditLogger(db).record(
        action="account.delete",
        user_id=current_user.id,
        target_type="user",
        target_id=str(current_user.id),
        ip_address=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )

    await db.commit()

    return {
        "message": "Account deleted",
        "deleted_utc": deleted_utc.isoformat(),
    }


@router.post("/export")
async def export_account_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR data portability.

    Returns all of the user's data as JSON. Writes one audit_log row
    with action='account.export'.

    Returns:
        The dict from UserRepository.export_account_data(user_id), shaped as
        {
            "user": {...},
            "interests": [...],
            "alerts": [...],
            "saved_trips": [...],
            "dismissed_trips": [...],
            "audit_log": [...],
        }
    """
    repo = UserRepository(db)

    try:
        data = await repo.export_account_data(current_user.id)
    except ValueError as exc:
        # User id from JWT no longer matches a row in the DB — extremely
        # unusual (the dep already loaded the user) but surface as 404.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    await AuditLogger(db).record(
        action="account.export",
        user_id=current_user.id,
        target_type="user",
        target_id=str(current_user.id),
        ip_address=request.client.host if request.client else None,
        request_id=getattr(request.state, "request_id", None),
    )

    await db.commit()

    return data


@router.get("/audit")
async def get_audit_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    """Return the current user's audit log rows, ordered most-recent first.

    `limit` is hard-capped at 200 to keep response payloads bounded.
    """
    capped = min(max(limit, 1), 200)
    rows = await AuditLogger(db).query(user_id=current_user.id, limit=capped)

    return [
        {
            "id": str(r.id),
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "source": r.source,
            "ip_address": r.ip_address,
            "request_id": r.request_id,
            "occurred_utc": r.occurred_utc.isoformat() if r.occurred_utc else None,
        }
        for r in rows
    ]
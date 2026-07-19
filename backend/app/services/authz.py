"""Authorization services: roles, permissions, require_permission dep."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)


class PermissionDenied(HTTPException):
    def __init__(self, perm: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing permission: {perm}",
        )


async def get_user_permissions(
    session: AsyncSession, user_id: UUID
) -> set[str]:
    """Return the set of permission keys the user currently has via non-revoked roles."""
    stmt = (
        select(Permission.key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
    )
    rows = await session.execute(stmt)
    return {row[0] for row in rows.all()}


async def get_user_roles(
    session: AsyncSession, user_id: UUID
) -> list[Role]:
    """Return the user's active (non-revoked) roles."""
    stmt = (
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def grant_role(
    session: AsyncSession,
    *,
    user_id: UUID,
    role_id: UUID,
    granted_by: UUID | None,
) -> UserRole:
    """Grant a role to a user. Idempotent: returns existing if already active."""
    stmt = select(UserRole).where(
        UserRole.user_id == user_id,
        UserRole.role_id == role_id,
        UserRole.revoked_at.is_(None),
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    role = UserRole(user_id=user_id, role_id=role_id, granted_by=granted_by)
    session.add(role)
    await session.flush()
    return role


async def revoke_role(
    session: AsyncSession,
    *,
    user_id: UUID,
    role_id: UUID,
) -> bool:
    """Revoke a role. Returns True if anything changed."""
    from datetime import datetime, timezone

    stmt = select(UserRole).where(
        UserRole.user_id == user_id,
        UserRole.role_id == role_id,
        UserRole.revoked_at.is_(None),
    )
    role_link = (await session.execute(stmt)).scalar_one_or_none()
    if role_link is None:
        return False
    role_link.revoked_at = datetime.now(timezone.utc)
    await session.flush()
    return True


async def user_has_permission(
    session: AsyncSession,
    user_id: UUID,
    perm: str,
) -> bool:
    perms = await get_user_permissions(session, user_id)
    return perm in perms


# -----------------------------------------------------------------------------
# FastAPI dependency: require_permission("user.create")
# -----------------------------------------------------------------------------

class CurrentUser:
    """Lightweight wrapper. Populated by get_current_user()."""

    def __init__(self, user: User) -> None:
        self.user = user
        self.id = user.id


# Re-export get_current_user from app.routers.auth for callers that prefer
# ``from app.services.authz import get_current_user``. The real implementation
# lives in app.routers.auth; this is not a circular import because auth.py
# does not import from this module.
from app.routers.auth import get_current_user as get_current_user  # noqa: F401


def require_permission(perm: str):
    """Returns a FastAPI dependency that 403s if the user lacks ``perm``."""

    async def _dep(
        session: Annotated[AsyncSession, Depends(get_session)],
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if not await user_has_permission(session, user.id, perm):
            raise PermissionDenied(perm)
        return user

    _dep.__name__ = f"require_{perm.replace('.', '_')}"
    return _dep


async def write_audit_log(
    session: AsyncSession,
    *,
    actor_user_id: UUID | None,
    action: str,
    target_kind: str | None = None,
    target_id: str | None = None,
    metadata: dict | None = None,
    request_id: str | None = None,
    actor_kind: ActorKind = ActorKind.ADMIN,
) -> AuditLog:
    """Append an audit-log row. Caller commits.

    Usage: call this just before returning from a mutating admin endpoint, and
    the caller's ``await session.commit()`` persists both the change and the
    log entry in one transaction.
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        metadata_json=metadata or {},
        request_id=request_id,
    )
    session.add(entry)
    await session.flush()
    return entry
"""Authorization services: roles, permissions, require_permission dep."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
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


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:  # real impl reads Bearer token from request; stub for foundation card
    raise NotImplementedError("register an auth router in the user-journey card")


def require_permission(perm: str):
    """Returns a FastAPI dependency that 403s if the user lacks ``perm``."""

    async def _dep(
        session: Annotated[AsyncSession, Depends(get_session)],
        # current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        # Placeholder: in foundation card, this is exercised by tests via direct
        # call to ``user_has_permission``; the full dep chain lands with the
        # auth router in t3_user_journey.
        raise NotImplementedError("auth router lands in t3_user_journey")

    _dep.__name__ = f"require_{perm.replace('.', '_')}"
    return _dep
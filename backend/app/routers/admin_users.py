"""Admin user management endpoints.

All endpoints require ``user.read`` at minimum. Mutations require the
appropriate perm (user.update, user.block, user.grant_role).

Every mutation writes an audit log entry in the same transaction.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import (
    ActorKind,
    Role,
    SavedItinerary,
    Subscription,
    SubscriptionTier,
    User,
    UserRole,
)
from app.services.authz import (
    grant_role,
    require_permission,
    revoke_role,
    write_audit_log,
)

router = APIRouter(prefix="/admin/users", tags=["admin"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------


class UserSummary(BaseModel):
    id: str
    email: str
    name: str
    is_active: bool
    tier: SubscriptionTier
    roles: list[str]
    created_at: str


class UserDetail(UserSummary):
    updated_at: str
    stripe_customer_id: str | None
    interests_count: int
    itineraries_count: int
    subscription_status: str | None


class UsersList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[UserSummary]


class GrantRoleRequest(BaseModel):
    role_key: str = Field(min_length=1, max_length=64)


class UpdateUserRequest(BaseModel):
    is_active: bool | None = None
    tier: SubscriptionTier | None = None
    name: str | None = Field(default=None, max_length=255)


# -----------------------------------------------------------------------------
# List + detail
# -----------------------------------------------------------------------------


@router.get("", response_model=UsersList)
async def list_users(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("user.read"))],
    q: str | None = Query(default=None, description="Search by email or name"),
    tier: SubscriptionTier | None = None,
    is_active: bool | None = None,
    role_key: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if q:
        like = f"%{q}%"
        cond = or_(User.email.ilike(like), User.name.ilike(like))
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    if tier is not None:
        stmt = stmt.where(User.tier == tier)
        count_stmt = count_stmt.where(User.tier == tier)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
        count_stmt = count_stmt.where(User.is_active == is_active)
    if role_key:
        stmt = stmt.join(UserRole, UserRole.user_id == User.id).join(
            Role, Role.id == UserRole.role_id
        ).where(Role.key == role_key, UserRole.revoked_at.is_(None))
        count_stmt = count_stmt.join(UserRole, UserRole.user_id == User.id).join(
            Role, Role.id == UserRole.role_id
        ).where(Role.key == role_key, UserRole.revoked_at.is_(None))

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset))
    ).scalars().all()

    # Fetch roles for the page (one extra query — N is small at limit=200)
    user_ids = [r.id for r in rows]
    role_map: dict[UUID, list[str]] = {uid: [] for uid in user_ids}
    if user_ids:
        role_rows = await session.execute(
            select(UserRole.user_id, Role.key)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                UserRole.user_id.in_(user_ids),
                UserRole.revoked_at.is_(None),
            )
        )
        for uid, rkey in role_rows.all():
            role_map.setdefault(uid, []).append(rkey)

    return UsersList(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            UserSummary(
                id=str(r.id),
                email=r.email,
                name=r.name,
                is_active=r.is_active,
                tier=r.tier,
                roles=role_map.get(r.id, []),
                created_at=r.created_at.isoformat(),
            )
            for r in rows
        ],
    )


@router.get("/{user_id}", response_model=UserDetail)
async def get_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("user.read"))],
    user_id: UUID,
):
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    role_rows = await session.execute(
        select(Role.key)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
    )
    roles = [r[0] for r in role_rows.all()]

    interests_count = (await session.execute(
        select(func.count()).select_from(SavedItinerary).where(SavedItinerary.user_id == user_id)
    )).scalar_one()  # placeholder; real interest count needs its own model — we surface itineraries_count instead
    # ^ That's actually itineraries count due to a model-name collision in the original code; we
    # use the real one below.
    itineraries_count = interests_count

    sub = (await session.execute(
        select(Subscription).where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    return UserDetail(
        id=str(user.id),
        email=user.email,
        name=user.name,
        is_active=user.is_active,
        tier=user.tier,
        roles=roles,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat(),
        stripe_customer_id=user.stripe_customer_id,
        interests_count=0,  # actual count requires UserInterest table — left at 0 for now
        itineraries_count=itineraries_count,
        subscription_status=sub.status.value if sub else None,
    )


# -----------------------------------------------------------------------------
# Mutations
# -----------------------------------------------------------------------------


@router.patch("/{user_id}", response_model=UserSummary)
async def update_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("user.update"))],
    user_id: UUID,
    body: UpdateUserRequest,
):
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    changes: dict = {}
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = {"from": user.is_active, "to": body.is_active}
        user.is_active = body.is_active
    if body.tier is not None and body.tier != user.tier:
        changes["tier"] = {"from": user.tier.value, "to": body.tier.value}
        user.tier = body.tier
    if body.name is not None and body.name != user.name:
        changes["name"] = {"from": user.name, "to": body.name}
        user.name = body.name

    if not changes:
        # No-op: still return current state without audit entry
        roles = await _fetch_role_keys(session, user_id)
        return UserSummary(
            id=str(user.id), email=user.email, name=user.name,
            is_active=user.is_active, tier=user.tier, roles=roles,
            created_at=user.created_at.isoformat(),
        )

    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="user.update",
        target_kind="user",
        target_id=str(user.id),
        metadata={"changes": changes},
        actor_kind=ActorKind.ADMIN,
    )
    await session.commit()

    roles = await _fetch_role_keys(session, user_id)
    return UserSummary(
        id=str(user.id), email=user.email, name=user.name,
        is_active=user.is_active, tier=user.tier, roles=roles,
        created_at=user.created_at.isoformat(),
    )


@router.post("/{user_id}/roles", status_code=status.HTTP_201_CREATED)
async def grant_user_role(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("user.grant_role"))],
    user_id: UUID,
    body: GrantRoleRequest,
):
    target_user = (await session.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="user not found")

    role = (await session.execute(
        select(Role).where(Role.key == body.role_key)
    )).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail=f"role not found: {body.role_key}")

    link = await grant_role(
        session, user_id=user_id, role_id=role.id, granted_by=admin.id,
    )
    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="user.grant_role",
        target_kind="user",
        target_id=str(user_id),
        metadata={"role_key": body.role_key},
    )
    await session.commit()
    return {"user_id": str(user_id), "role_key": body.role_key, "granted_at": link.granted_at.isoformat()}


@router.delete("/{user_id}/roles/{role_key}", status_code=status.HTTP_200_OK)
async def revoke_user_role(
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[User, Depends(require_permission("user.grant_role"))],
    user_id: UUID,
    role_key: str,
):
    role = (await session.execute(
        select(Role).where(Role.key == role_key)
    )).scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail=f"role not found: {role_key}")

    changed = await revoke_role(session, user_id=user_id, role_id=role.id)
    if not changed:
        raise HTTPException(status_code=404, detail="user does not have this role (or already revoked)")

    await write_audit_log(
        session,
        actor_user_id=admin.id,
        action="user.revoke_role",
        target_kind="user",
        target_id=str(user_id),
        metadata={"role_key": role_key},
    )
    await session.commit()
    return {"user_id": str(user_id), "role_key": role_key, "revoked": True}


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _fetch_role_keys(session: AsyncSession, user_id: UUID) -> list[str]:
    rows = await session.execute(
        select(Role.key)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))
    )
    return [r[0] for r in rows.all()]

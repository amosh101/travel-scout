"""Tier guard: enforce per-tier limits at the service layer.

The tier guard is called from routers (not middleware) so that business logic
can return structured 4xx errors with actionable detail.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    SubscriptionTier,
    TierLimit,
    UsageCounter,
)


class TierLimitExceeded(HTTPException):
    def __init__(self, *, tier: str, action: str, current: int, limit: int) -> None:
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "tier_limit_exceeded",
                "tier": tier,
                "action": action,
                "current": current,
                "limit": limit,
                "next_step": "upgrade at /api/billing/checkout",
            },
        )


@dataclass(frozen=True)
class TierCheck:
    allowed: bool
    current: int
    limit: int
    detail: str | None = None


def current_period_yyyymm() -> int:
    now = datetime.now(timezone.utc)
    return now.year * 100 + now.month


async def _get_tier_limit(session: AsyncSession, tier: SubscriptionTier) -> TierLimit:
    stmt = select(TierLimit).where(TierLimit.tier == tier)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError(f"tier limit not seeded for {tier}; run scripts/seed_reference")
    return row


async def _get_or_create_counter(
    session: AsyncSession,
    user_id,
    period: int,
) -> UsageCounter:
    stmt = select(UsageCounter).where(
        UsageCounter.user_id == user_id,
        UsageCounter.period_yyyymm == period,
    )
    counter = (await session.execute(stmt)).scalar_one_or_none()
    if counter is not None:
        return counter
    counter = UsageCounter(user_id=user_id, period_yyyymm=period)
    session.add(counter)
    await session.flush()
    return counter


async def check_tier_limit(
    session: AsyncSession,
    *,
    user_id,
    tier: SubscriptionTier,
    action: Literal["save", "search"],
) -> TierCheck:
    """Return whether the user is allowed to perform ``action`` under their tier.

    Does NOT increment counters — call ``record_usage`` after success.
    """
    tier_limit = await _get_tier_limit(session, tier)
    period = current_period_yyyymm()
    counter = await _get_or_create_counter(session, user_id, period)
    if action == "save":
        current = counter.saves
        limit = tier_limit.max_saved_per_month
    elif action == "search":
        current = counter.searches
        limit = tier_limit.max_searches_per_month
    else:
        raise ValueError(f"unknown action: {action!r}")

    # limit == -1 means "unlimited on this tier"
    if limit == -1:
        return TierCheck(True, current, -1, None)

    # limit == 0 means "feature disabled on this tier"
    if limit <= 0:
        return TierCheck(False, current, limit, f"{action} not available on tier {tier.value}")

    if current >= limit:
        return TierCheck(False, current, limit, f"{tier.value} tier capped at {limit}/{action}/month")

    return TierCheck(True, current, limit, None)


async def record_usage(
    session: AsyncSession,
    *,
    user_id,
    action: Literal["save", "search"],
) -> None:
    """Bump the appropriate counter for the current period."""
    period = current_period_yyyymm()
    counter = await _get_or_create_counter(session, user_id, period)
    if action == "save":
        counter.saves += 1
    elif action == "search":
        counter.searches += 1
    else:
        raise ValueError(f"unknown action: {action!r}")
    await session.flush()


async def require_tier_allows(
    session: AsyncSession,
    *,
    user_id,
    tier: SubscriptionTier,
    action: Literal["save", "search"],
) -> None:
    """Raise TierLimitExceeded if the user cannot perform ``action``."""
    check = await check_tier_limit(
        session, user_id=user_id, tier=tier, action=action
    )
    if not check.allowed:
        raise TierLimitExceeded(
            tier=tier.value,
            action=action,
            current=check.current,
            limit=check.limit,
        )
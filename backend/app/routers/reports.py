"""Reports + digest endpoints (2026-10-21).

ADMIN (permission report.read): usage / trips / finance / resources.
AGENT (permission agent.work): my reports + my audit trail.
USER: GET /api/me/digests (in-app weekly delivery).

All numbers come from REAL rows — audit_log, bookings_log,
saved_itineraries, usage_counters, digests, stripe_events. Nothing is
extrapolated; empty aggregates are honest. Resource usage reads
/proc + DB/Redis sizes (stdlib only, no new dependencies).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    BookingsLog,
    Digest,
    SavedItinerary,
    StripeEvent,
    Subscription,
    SubscriptionStatus,
    UsageCounter,
    User,
    UserInterest,
)
from app.services.authz import get_current_user, require_permission

router = APIRouter(tags=["reports"])

_DAYS = Query(default=30, ge=1, le=365)


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


# -----------------------------------------------------------------------------
# ADMIN — usage
# -----------------------------------------------------------------------------


@router.get("/admin/reports/usage")
async def report_usage(
    days: int = _DAYS,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_permission("report.read")),
) -> dict:
    since = _since(days)
    rows = (await session.execute(
        select(
            func.date(AuditLog.at).label("day"),
            AuditLog.action.label("action"),
            func.count(AuditLog.id).label("n"),
        )
        .where(AuditLog.at >= since)
        .group_by("day", "action")
        .order_by("day")
    )).all()
    daily: dict[str, dict[str, int]] = {}
    for day, action, n in rows:
        daily.setdefault(str(day), {})[action] = int(n)

    key_actions = [
        "user.login", "user.register", "itineraries.discover",
        "itinerary.save", "agent.handoff", "agent.payment.recorded",
        "agent.outcome.confirmed", "message.post",
    ]
    totals = {a: sum(b.get(a, 0) for b in daily.values()) for a in key_actions}

    users_total = (await session.execute(
        select(func.count()).select_from(User)
    )).scalar_one()
    users_active = (await session.execute(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )).scalar_one()
    tiers = (await session.execute(
        select(User.tier, func.count()).group_by(User.tier)
    )).all()

    # Tier-guard counters for the current month (real search/save usage).
    period = int(f"{datetime.now(timezone.utc):%Y%m}")
    month_usage = (await session.execute(
        select(User.tier, func.sum(UsageCounter.searches), func.sum(UsageCounter.saves))
        .join(UsageCounter, UsageCounter.user_id == User.id)
        .where(UsageCounter.period_yyyymm == period)
        .group_by(User.tier)
    )).all()

    return {
        "window_days": days,
        "users_total": users_total,
        "users_active": users_active,
        "tier_distribution": {
            (t.value if hasattr(t, "value") else str(t)): n for t, n in tiers
        },
        "month_usage_by_tier": [
            {
                "tier": (t.value if hasattr(t, "value") else str(t)),
                "searches": int(s or 0),
                "saves": int(v or 0),
            }
            for t, s, v in month_usage
        ],
        "action_totals": totals,
        "daily": daily,
    }


# -----------------------------------------------------------------------------
# ADMIN — trips
# -----------------------------------------------------------------------------


@router.get("/admin/reports/trips")
async def report_trips(
    days: int = _DAYS,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_permission("report.read")),
) -> dict:
    since = _since(days)
    saved_total = (await session.execute(
        select(func.count()).select_from(SavedItinerary)
    )).scalar_one()
    saved_in_window = (await session.execute(
        select(func.count()).select_from(SavedItinerary)
        .where(SavedItinerary.created_at >= since)
    )).scalar_one()

    # Top destinations (denormalised name lives in the payload JSON).
    handoffs_by_status = (await session.execute(
        select(BookingsLog.status, func.count(BookingsLog.id))
        .where(BookingsLog.created_at >= since)
        .group_by(BookingsLog.status)
    )).all()
    handoffs_total = sum(int(n) for _, n in handoffs_by_status)
    confirmed = sum(int(n) for s, n in handoffs_by_status if s == "confirmed")

    digests_sent = (await session.execute(
        select(func.count()).select_from(Digest).where(Digest.created_at >= since)
    )).scalar_one()

    return {
        "window_days": days,
        "itineraries_saved_total": saved_total,
        "itineraries_saved_in_window": saved_in_window,
        "handoffs": {
            "total": handoffs_total,
            "by_status": {s: int(n) for s, n in handoffs_by_status},
            "confirmed": confirmed,
            "confirmation_rate":
                round(confirmed / handoffs_total, 3) if handoffs_total else None,
        },
        "digests_generated_in_window": digests_sent,
    }


# -----------------------------------------------------------------------------
# ADMIN — finance
# -----------------------------------------------------------------------------


@router.get("/admin/reports/finance")
async def report_finance(
    days: int = _DAYS,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_permission("report.read")),
) -> dict:
    since = _since(days)
    # Agent-recorded payments (money handled off-platform).
    paid_rows = (await session.execute(
        select(
            BookingsLog.currency,
            func.count(BookingsLog.id),
            func.sum(BookingsLog.amount_cents),
            func.sum(BookingsLog.commission_cents),
        )
        .where(BookingsLog.paid_at >= since)
        .group_by(BookingsLog.currency)
    )).all()
    payments = [
        {
            "currency": cur,
            "bookings": int(n),
            "amount_cents": int(tot or 0),
            "commission_cents": int(comm or 0),
        }
        for cur, n, tot, comm in paid_rows
    ]
    payment_statuses = (await session.execute(
        select(BookingsLog.payment_status, func.count(BookingsLog.id))
        .group_by(BookingsLog.payment_status)
    )).all()

    # Platform subscriptions: current base + invoice revenue from real
    # Stripe events (invoice.paid payloads carry Stripe's amounts).
    subs = (await session.execute(
        select(Subscription.tier, Subscription.status, func.count(Subscription.id))
        .group_by(Subscription.tier, Subscription.status)
    )).all()
    invoices = (await session.execute(
        select(StripeEvent.payload)
        .where(StripeEvent.event_type == "invoice.paid")
        .where(StripeEvent.received_at >= since)
    )).scalars().all()
    revenue_by_currency: dict[str, int] = {}
    for payload in invoices:
        inv = (payload or {}).get("data", {}).get("object", {})
        cur = str(inv.get("currency", "usd")).upper()
        amount = int(inv.get("amount_paid") or 0)
        revenue_by_currency[cur] = revenue_by_currency.get(cur, 0) + amount

    return {
        "window_days": days,
        "agent_payments_by_currency": payments,
        "payment_status_counts": {s: int(n) for s, n in payment_statuses},
        "subscriptions": [
            {"tier": (t.value if hasattr(t, "value") else str(t)),
             "status": (s.value if hasattr(s, "value") else str(s)),
             "count": int(n)}
            for t, s, n in subs
        ],
        "subscription_revenue_by_currency": revenue_by_currency,
        "note": "agent payments are recorded off-platform and audited in-app; "
        "subscription revenue is what Stripe actually invoiced",
    }


# -----------------------------------------------------------------------------
# ADMIN — resources
# -----------------------------------------------------------------------------


def _proc_cpu_seconds() -> float:
    try:
        with open("/proc/self/stat", "rb") as f:
            parts = f.read().split()
        # fields 14,15 (1-indexed) = utime, stime in clock ticks
        ticks = os.sysconf("SC_CLK_TCK")
        return (float(parts[13]) + float(parts[14])) / ticks
    except Exception:  # noqa: BLE001
        return 0.0


@router.get("/admin/reports/resources")
async def report_resources(
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_permission("report.read")),
) -> dict:
    settings = get_settings()
    cpu1 = _proc_cpu_seconds()
    import asyncio as _a

    await _a.sleep(0.25)
    cpu2 = _proc_cpu_seconds()
    os_pid_cpu_pct = round((cpu2 - cpu1) / 0.25 * 100, 2)

    mem = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(("MemTotal", "MemAvailable")):
                    k, v = line.split(":")
                    mem[k] = int(v.split()[0]) * 1024
    except Exception:  # noqa: BLE001
        pass
    rss = 0
    try:
        with open("/proc/self/statm") as f:
            rss = int(f.read().split()[1]) * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:  # noqa: BLE001
        pass

    # Host-visible usage numbers that need DB access.
    db_size = (await session.execute(
        text("SELECT pg_database_size(current_database())")
    )).scalar_one()
    row_counts = {}
    for table in ("users", "saved_itineraries", "bookings_log", "messages",
                  "audit_log", "digests", "stripe_events", "usage_counters"):
        row_counts[table] = (await session.execute(
            text(f"SELECT count(*) FROM {table}")  # fixed whitelist, no user input
        )).scalar_one()

    media_bytes = 0
    try:
        for root, _dirs, files in os.walk(settings.media_root):
            media_bytes += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    except Exception:  # noqa: BLE001
        pass

    queue_depth = (await session.execute(
        select(func.count()).select_from(BookingsLog)
        .where(BookingsLog.status.in_(("pending", "claimed", "in_progress")))
    )).scalar_one()

    return {
        "api_pid_cpu_pct": os_pid_cpu_pct,
        "api_rss_bytes": rss,
        "host_mem": mem,
        "api_cpu_seconds_total": cpu2,
        "cpu_cores": os.cpu_count(),
        "database_bytes": int(db_size or 0),
        "row_counts": row_counts,
        "media_bytes": media_bytes,
        "open_queue_items": queue_depth,
        "digest_scheduler_enabled": settings.digests_enabled,
    }


# -----------------------------------------------------------------------------
# ADMIN — digest trigger (manual backstop for the weekly scheduler)
# -----------------------------------------------------------------------------


@router.post("/admin/digest/run")
async def admin_digest_run(
    body: dict | None = None,
    session: AsyncSession = Depends(get_session),
    _: User = Depends(require_permission("report.read")),
) -> dict:
    """Force the weekly digest for one user (user_id) or all due users."""
    from app.jobs.scheduler import build_and_store_digest, run_due_digests

    user_id = (body or {}).get("user_id")
    if user_id:
        user = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        out = [await build_and_store_digest(session, user, force=True)]
    else:
        out = await run_due_digests()
    await AuditLog_helper(session)
    return {"ran": len(out), "results": out}


async def AuditLog_helper(session: AsyncSession) -> None:
    from app.services.audit import AuditService

    await AuditService.record(
        session,
        actor_user_id=None,
        actor_kind=ActorKind.SYSTEM,
        action="admin.digest.run",
        target_kind="digests",
        target_id=None,
    )
    await session.commit()


# -----------------------------------------------------------------------------
# USER — my digests
# -----------------------------------------------------------------------------


@router.get("/me/digests")
async def my_digests(
    limit: int = Query(default=8, ge=1, le=26),
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    rows = (await session.execute(
        select(Digest)
        .where(Digest.user_id == user.id)
        .order_by(Digest.week_of.desc())
        .limit(limit)
    )).scalars().all()
    return {
        "optout": bool(getattr(user, "digest_optout", False)),
        "items": [
            {
                "id": str(r.id),
                "week_of": str(r.week_of),
                "window": r.window,
                "payload": r.payload,
                "sent_email": r.sent_email,
                "email_status": r.email_status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


# -----------------------------------------------------------------------------
# AGENT — my reports + my audit trail
# -----------------------------------------------------------------------------


@router.get("/agent/reports/me")
async def agent_report(
    days: int = _DAYS,
    session: AsyncSession = Depends(get_session),
    agent: User = Depends(require_permission("agent.work")),
) -> dict:
    since = _since(days)
    mine = (await session.execute(
        select(
            BookingsLog.status,
            func.count(BookingsLog.id),
            func.sum(BookingsLog.amount_cents),
            func.sum(BookingsLog.commission_cents),
        )
        .where(BookingsLog.assigned_agent_id == agent.id)
        .group_by(BookingsLog.status)
    )).all()
    by_status = {
        s: {
            "count": int(n),
            "amount_cents": int(tot or 0),
            "commission_cents": int(comm or 0),
        }
        for s, n, tot, comm in mine
    }
    payments_by_currency = (await session.execute(
        select(BookingsLog.currency, func.count(), func.sum(BookingsLog.amount_cents))
        .where(BookingsLog.assigned_agent_id == agent.id)
        .where(BookingsLog.paid_at >= since)
        .group_by(BookingsLog.currency)
    )).all()
    my_messages = (await session.execute(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.actor_user_id == agent.id)
        .where(AuditLog.action == "message.post")
    )).scalar_one()
    my_handoffs = (await session.execute(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.actor_user_id == agent.id)
        .where(AuditLog.action.in_(("agent.handoff", "agent.outcome.confirmed",
                                    "agent.outcome.failed", "agent.payment.recorded",
                                    "agent.claim", "agent.release")))
    )).scalar_one()
    claimed_total = (await session.execute(
        select(func.count()).select_from(BookingsLog)
        .where(BookingsLog.assigned_agent_id == agent.id)
    )).scalar_one()
    pending_pool = (await session.execute(
        select(func.count()).select_from(BookingsLog)
        .where(BookingsLog.status == "pending")
    )).scalar_one()

    return {
        "window_days": days,
        "queue": {"claimed_by_me_total": claimed_total, "pending_pool": pending_pool},
        "bookings_by_status": by_status,
        "payments_by_currency_in_window": [
            {"currency": cur, "count": int(n), "amount_cents": int(tot or 0)}
            for cur, n, tot in payments_by_currency
        ],
        "actions_in_window": {
            "threads_posted": my_messages,
            "handoff_lifecycle_actions": my_handoffs,
        },
    }


@router.get("/agent/audit")
async def agent_audit(
    limit: int = Query(default=200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    agent: User = Depends(require_permission("agent.work")),
) -> dict:
    """The agent's OWN actions only — least-privilege audit visibility."""
    rows = (await session.execute(
        select(AuditLog)
        .where(AuditLog.actor_user_id == agent.id)
        .where(AuditLog.actor_kind == ActorKind.AGENT)
        .order_by(AuditLog.at.desc())
        .limit(limit)
    )).scalars().all()
    total = (await session.execute(
        select(func.count()).select_from(AuditLog)
        .where(AuditLog.actor_user_id == agent.id)
        .where(AuditLog.actor_kind == ActorKind.AGENT)
    )).scalar_one()
    return {
        "total": total,
        "items": [
            {
                "id": str(r.id),
                "action": r.action,
                "target_kind": r.target_kind,
                "target_id": r.target_id,
                "metadata": r.metadata_json,
                "at": r.at.isoformat(),
            }
            for r in rows
        ],
    }
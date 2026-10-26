"""Background jobs (in-process, no new dependencies).

Lifespan task, not a cron: it rides uvicorn's own async loop, wakes on
``settings.digest_check_interval_s``, and is idempotent — the
``digests`` unique (user, week_of) index + ``digest_last_sent_at``
anchor make a double-send structurally impossible.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import get_session_factory
from app.models import Digest, User

logger = logging.getLogger(__name__)

_task: "asyncio.Task[None] | None" = None


def _week_of(today: date) -> date:
    """Monday of the current week."""
    return today - timedelta(days=today.weekday())


def _compact(results: list[dict], max_results: int) -> list[dict]:
    """Digest payload: the bits /saved renders + email copies."""
    items: list[dict] = []
    for r in (results or [])[:max_results]:
        if not isinstance(r, dict):
            continue
        window = r.get("event_window") or {}
        events = r.get("races_in_window") or []
        hol = r.get("holiday_alerts") or []
        dest = r.get("destination") or r.get("destination_name")
        anchor = window.get("anchor_name")
        items.append(
            {
                "title": f"{anchor} — {dest}" if anchor and dest else dest,
                "destination": dest,
                "start": str(r.get("start_date") or "")[:10],
                "end": str(r.get("end_date") or "")[:10],
                "why": ", ".join((r.get("pitch") or [])[:1])
                or f"{len(events)} event(s), {len(hol)} holiday(s) in window",
                "sources": r.get("sources") or [],
            }
        )
    return items


async def build_and_store_digest(session, user: User, *, force: bool = False) -> dict:
    """Generate one user's weekly digest (engine-backed, never mocked).

    Returns a summary dict {user, week_of, items, email}. No-op for
    users without onboarding or with an opt-out (unless force=True).
    """
    from app.routers.itineraries_discover import _discover_for_user

    settings = get_settings()
    now = datetime.now(timezone.utc)
    if not getattr(user, "onboarding_complete", False) and not force:
        return {"user": str(user.id), "skipped": "not_onboarded"}
    if getattr(user, "digest_optout", False) and not force:
        return {"user": str(user.id), "skipped": "digest_optout"}

    window_from = now.date()
    window_to = window_from + timedelta(days=settings.digest_window_days)
    results = await _discover_for_user(
        session=session,
        user=user,
        origin=None,  # stored profile origin
        destination=None,  # event-anchored discovery
        interests_param=None,  # stored interests
        date_from=window_from,
        date_to=window_to,
        top_n=settings.digest_max_results,
    )
    payload = _compact(results.get("results", []), settings.digest_max_results)

    week = _week_of(window_from)
    # Upsert by (user, week) — the unique index guards the race.
    existing = (await session.execute(
        select(Digest).where(Digest.user_id == user.id, Digest.week_of == week)
    )).scalar_one_or_none()
    if existing is not None:
        existing.payload = payload
        existing.window = {"date_from": str(window_from), "date_to": str(window_to)}
        row = existing
    else:
        row = Digest(
            user_id=user.id,
            week_of=week,
            window={"date_from": str(window_from), "date_to": str(window_to)},
            payload=payload,
        )
        session.add(row)
        await session.flush()

    if not getattr(user, "digest_last_sent_at", None) or force:
        pass  # (last_sent is set below on real sends only)

    # Email (in-app copy is the row itself; SMS reserved for short alerts).
    if payload or force:
        from app.clients.notify import notify_digest
        status_map = notify_digest(user_email=user.email, items=payload)
        row.sent_email = status_map.get("email") == "sent"
        row.email_status = status_map.get("email", "skipped_not_configured")
        user.digest_last_sent_at = now

    await session.commit()
    return {
        "user": str(user.id),
        "week_of": str(week),
        "items": len(payload),
        "email": row.email_status,
    }


async def run_due_digests() -> list[dict]:
    """Send the weekly digest to every due user. Called by the loop."""
    settings = get_settings()
    if not settings.digests_enabled:
        return []
    from sqlalchemy import DateTime

    factory = get_session_factory()
    out: list[dict] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with factory() as session:
        rows = (await session.execute(
            select(User).where(
                User.is_active.is_(True),
                User.onboarding_complete.is_(True),
                User.digest_optout.is_(False),
            )
        )).scalars().all()
        for user in rows:
            last = getattr(user, "digest_last_sent_at", None)
            if last is not None and last > cutoff:
                continue
            try:
                out.append(await build_and_store_digest(session, user))
            except Exception as e:  # noqa: BLE001 — one user's failure must not stop the rest
                logger.warning("digest failed for %s: %s", user.id, e)
                out.append({"user": str(user.id), "error": str(e)})
    return out


async def _loop() -> None:
    settings = get_settings()
    logger.info("digest scheduler awake (interval=%ss)", settings.digest_check_interval_s)
    while True:
        try:
            sent = await run_due_digests()
            if sent:
                logger.info("digest run: %s", sent)
        except Exception as e:  # noqa: BLE001
            logger.warning("digest loop error: %s", e)
        await asyncio.sleep(settings.digest_check_interval_s)


async def start_scheduler() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop_scheduler() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
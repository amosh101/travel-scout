"""One-time seeder: writes INTEREST_CATALOG rows into the ``interests`` table.

Idempotent. Re-runnable any time. Used to fix the catalog-vs-DB mismatch
where the Python INTEREST_CATALOG list is the source of truth but the
DB only had a few rows from registrations.

Run: ``python -m app.scripts.seed_interest_catalog``
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.database import get_session_factory
from app.models import Interest
from app.routers.profile import INTEREST_CATALOG

logger = logging.getLogger(__name__)


async def main() -> dict[str, int]:
    """Upsert every INTEREST_CATALOG entry into the interests table.

    Returns ``{"created", "updated", "skipped"}`` counts.
    """
    factory = get_session_factory()
    created = updated = skipped = 0
    async with factory() as session:
        for entry in INTEREST_CATALOG:
            existing = (
                await session.execute(
                    select(Interest).where(Interest.key == entry["key"])
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(Interest(
                    key=entry["key"],
                    name=entry["name"],
                    description="",
                    event_keywords=list(entry.get("event_keywords") or []),
                    kind=entry.get("kind"),
                ))
                created += 1
                continue
            # Update if name or keywords drifted. ``kind`` is the new
            # v3 field; populate it for legacy rows.
            changed = False
            if existing.name != entry["name"]:
                existing.name = entry["name"]
                changed = True
            if list(existing.event_keywords or []) != list(entry.get("event_keywords") or []):
                existing.event_keywords = list(entry.get("event_keywords") or [])
                changed = True
            if getattr(existing, "kind", None) != entry.get("kind"):
                existing.kind = entry.get("kind")
                changed = True
            if changed:
                updated += 1
            else:
                skipped += 1
        await session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(main()))

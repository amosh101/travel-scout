#!/usr/bin/env python3
"""Ingest free-event legs (Wikidata + Wikipedia) into the scraped_* ledger.

Run inside the api container (has the app deps):
    docker cp .audits/ingest_free_events.py <api>:/tmp/
    docker exec -w /app -e PYTHONPATH=/app <api> python /tmp/ingest_free_events.py

Writes ONLY to scraped_locations, scraped_events, scraped_runs (read
everything it needs from the live aggregator); never touches user tables.
Idempotent: ON CONFLICT upserts on (source, source_id, dedupe_year).
"""

import asyncio
import hashlib
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg

try:
    from app.config import get_settings
except ImportError:  # pragma: no cover
    from app.settings import get_settings

from app.clients.free_events import build_free_event_aggregator

# Catalog cities (destinations table snapshot 2026-10-26)
CITY_CC = {
    "Amsterdam": "NL",
    "Barcelona": "ES",
    "Florence": "IT",
    "Geneva": "CH",
    "London": "GB",
    "Madrid": "ES",
    "Milan": "IT",
    "Paris": "FR",
    "Rome": "IT",
    "Zurich": "CH",
}
INTEREST_KEYS = ["jazz", "electronic-music", "classical", "art-museums"]
WINDOW_DAYS = 90
PER_SEARCH_TIMEOUT_S = 45
TOTAL_BUDGET_S = 470  # stay under the 600s exec window with margin

DEST_TABLE = [
    ("Amsterdam", "Netherlands", "AMS"),
    ("Barcelona", "Spain", "BCN"),
    ("Florence", "Italy", "FLR"),
    ("Geneva", "Switzerland", "GVA"),
    ("London", "United Kingdom", "LHR"),
    ("Madrid", "Spain", "MAD"),
    ("Milan", "Italy", "MIL"),
    ("Paris", "France", "CDG"),
    ("Rome", "Italy", "FCO"),
    ("Zurich", "Switzerland", "ZRH"),
]

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def make_source_id(rec) -> str:
    sid = (rec.source_qid or "").strip()
    if not sid:
        tail = rec.starts_at.isoformat() if rec.starts_at else "nodate"
        sid = f"{(rec.name or '').lower().strip()}|{rec.city}|{tail}"
    if len(sid) > 128:
        sid = hashlib.sha1(sid.encode()).hexdigest()[:32]
    return sid


async def ensure_location(conn, city: str, cc: str, lat, lon, now, expires) -> uuid.UUID:
    loc_id = await conn.fetchval(
        """
        INSERT INTO scraped_locations
          (id, source, source_id, name, country_alpha2, latitude, longitude,
           scraped_at, expires_at)
        VALUES ($1,'location_resolver',$2,$3,$4,$5,$6,$7,$8)
        ON CONFLICT (source, source_id) DO UPDATE
          SET name=EXCLUDED.name, country_alpha2=EXCLUDED.country_alpha2,
              latitude=COALESCE(EXCLUDED.latitude, scraped_locations.latitude),
              longitude=COALESCE(EXCLUDED.longitude, scraped_locations.longitude),
              scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
        RETURNING id
        """,
        uuid.uuid4(), f"{cc}:{city}", city, cc, lat, lon, now, expires,
    )
    return loc_id


async def upsert_event(conn, rec, interest_key: str, loc_id, now, expires, stats_by_source):
    src = (rec.source or "free_events").strip() or "free_events"
    if src not in stats_by_source:
        stats_by_source[src] = {"added": 0, "updated": 0, "errors": 0}
    sid = make_source_id(rec)
    dedupe_year = rec.starts_at.year if rec.starts_at else None
    raw = {
        "source_url": rec.source_url or "",
        "city": rec.city or "",
        "country": rec.country or "",
        "extra": rec.extra or {},
    }
    inserted = await conn.fetchval(
        """
        INSERT INTO scraped_events
          (id, source, source_id, name, kind, interest_key, starts_at, ends_at,
           location_id, wikidata_qid, raw, scraped_at, expires_at, dedupe_year)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14)
        ON CONFLICT (source, source_id, dedupe_year) DO UPDATE
          SET name=EXCLUDED.name, kind=EXCLUDED.kind, interest_key=EXCLUDED.interest_key,
              starts_at=EXCLUDED.starts_at, ends_at=EXCLUDED.ends_at,
              location_id=EXCLUDED.location_id, wikidata_qid=EXCLUDED.wikidata_qid,
              raw=EXCLUDED.raw, scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
        RETURNING (xmax = 0)
        """,
        uuid.uuid4(), src, sid, (rec.name or "")[:512], (rec.kind or "")[:64],
        interest_key[:64], rec.starts_at, rec.ends_at, loc_id,
        (rec.source_qid or "")[:32], json.dumps(raw)[:4000], now, expires, dedupe_year,
    )
    if inserted:
        stats_by_source[src]["added"] += 1
    else:
        stats_by_source[src]["updated"] += 1


async def main() -> None:
    t0 = time.time()
    started_at = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    agg = build_free_event_aggregator()

    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now = now_utc()
    expires = now + timedelta(days=30)

    stats_by_source: dict[str, dict] = {}
    city_report: dict[str, dict] = {}
    partial = False

    try:
        for city, cc in CITY_CC.items():
            if time.time() - t0 > TOTAL_BUDGET_S:
                partial = True
                print(f"TIME BUDGET reached — stopping after {city}", flush=True)
                break
            cities_seen = city_report.setdefault(city, {"cc": cc, "events": 0, "samples": []})
            for key in INTEREST_KEYS:
                try:
                    records = await asyncio.wait_for(
                        agg.search(
                            key,
                            country_alpha2=cc,
                            start_date=start_d,
                            end_date=end_d,
                            city=city,
                            limit=50,
                        ),
                        timeout=PER_SEARCH_TIMEOUT_S,
                    )
                except Exception as exc:  # noqa: BLE001 — one bad leg must not stop the run
                    print(f"  [{city}/{key}] search failed: {type(exc).__name__}: {exc}", flush=True)
                    for s in ("wikidata", "wikipedia"):
                        stats_by_source.setdefault(s, {"added": 0, "updated": 0, "errors": 0})
                        if isinstance(exc, asyncio.TimeoutError):
                            stats_by_source[s]["errors"] += 1
                    continue
                if not records:
                    continue
                # location from the first record that carries coordinates
                lat = lon = None
                for r in records:
                    if r.latitude is not None and r.longitude is not None:
                        lat, lon = r.latitude, r.longitude
                        break
                loc_id = await ensure_location(conn, city, cc, lat, lon, now, expires)
                for r in records:
                    try:
                        await upsert_event(conn, r, key, loc_id, now, expires, stats_by_source)
                        cities_seen["events"] += 1
                        if len(cities_seen["samples"]) < 8:
                            cities_seen["samples"].append(
                                {"name": r.name[:100], "date": r.starts_at.isoformat() if r.starts_at else None,
                                 "kind": r.kind, "source": r.source}
                            )
                    except Exception as exc:  # noqa: BLE001
                        for s in ("wikidata", "wikipedia"):
                            stats_by_source.setdefault(s, {"added": 0, "updated": 0, "errors": 0})
                            stats_by_source[s]["errors"] += 1
                        print(f"  [{city}/{key}] row failed: {type(exc).__name__}: {exc}", flush=True)
                print(f"  [{city}] {key}: {len(records)} record(s)", flush=True)
    finally:
        finished_at = now_utc()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = "partial" if partial else "success"
        for src, s in sorted(stats_by_source.items()):
            await conn.execute(
                """
                INSERT INTO scraped_runs
                  (id, source, scraper, started_at, finished_at, status,
                   added, updated, error, duration_ms)
                VALUES ($1,$2,'FreeEventIngestScript',$3,$4,$5,$6,$7,$8,$9)
                """,
                uuid.uuid4(), src, started_at, finished_at, status,
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} per-search/row error(s)",
                duration_ms,
            )
        await conn.close()

    print(json.dumps({"status": status, "duration_ms": duration_ms,
                      "by_source": stats_by_source, "cities": city_report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
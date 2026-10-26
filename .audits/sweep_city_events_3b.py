#!/usr/bin/env python3
"""Pass 3b: continuation of pass 3.

- Retries the Wikidata term searches that hit HTTPError (rate limit) with
  per-call sleep + bounded retries.
- For every undated series candidate found in pass 3, follows P527
  ("has part") to dated editions and persists editions inside the window.
- Extra curated terms for Madrid / Milan.

Run inside the api container:
    docker exec -w /app -e PYTHONPATH=/app <api> python /tmp/sweep_city_events_3b.py
"""

import asyncio
import json
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg
from curl_cffi import requests as cffi_requests

try:
    from app.config import get_settings
except ImportError:  # pragma: no cover
    from app.settings import get_settings

UA = "travel-scout-city-sweep/3.1 (github.com/amosh101/travel-scout)"
API = "https://www.wikidata.org/w/api.php"
SLEEP_S = 1.5

SERIES = {
    # qid -> (city, cc, city_qid)
    "Q26156861": ("Amsterdam", "NL", "Q727"),   # Amsterdam Light Festival
    "Q1137736": ("Geneva", "CH", "Q71"),        # Course de l'Escalade
    "Q5121157": ("Geneva", "CH", "Q71"),        # Geneva Int'l Film Festival
    "Q125737552": ("Geneva", "CH", "Q71"),      # GIFF (edition item?)
}

TERMS = {
    "Madrid": ("ES", "Q2807", ["Jazz Madrid", "Madrid Christmas market",
                               "San Silvestre Vallecana"]),
    "Milan": ("IT", "Q490", ["Oh Bej! Oh Bej!", "Milan Christmas market"]),
}

WINDOW_DAYS = 150


def now_utc():
    return datetime.now(timezone.utc)


def polite(fn, *a, **kw):
    for attempt in (1, 2, 3, 4):
        try:
            time.sleep(SLEEP_S)
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            if attempt == 4:
                raise
            wait = 5 * attempt
            print(f"    retry {attempt} after {type(exc).__name__} "
                  f"(sleep {wait}s)", flush=True)
            time.sleep(wait)


def search_entities(term, limit=5):
    r = cffi_requests.get(API, params={
        "action": "wbsearchentities", "search": term, "language": "en",
        "format": "json", "type": "item", "limit": str(limit),
    }, headers={"User-Agent": UA}, impersonate="chrome120", timeout=15)
    r.raise_for_status()
    return r.json().get("search", [])


def get_entity(qid):
    r = cffi_requests.get(API, params={
        "action": "wbgetentities", "ids": qid, "props": "claims|labels",
        "languages": "en", "format": "json",
    }, headers={"User-Agent": UA}, impersonate="chrome120", timeout=15)
    r.raise_for_status()
    return r.json().get("entities", {}).get(qid, {})


def wiki_date(claims, props):
    """First well-formed date among the props. Wikidata zero-precision
    components (month 00 / day 00) are handled: month 00 -> reject,
    day 00 -> coerce to the 1st."""
    for pid in props:
        for cl in claims.get(pid, []):
            snak = cl.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue
            t = (snak.get("datavalue", {}).get("value", {}) or {}).get("time", "")
            m = re.match(r"([+-])(\d{4})-(\d{2})-(\d{2})", t)
            if m and m.group(1) != "-":
                year, month, day = (int(m.group(i)) for i in (2, 3, 4))
                if month == 0:
                    continue
                day = day if day >= 1 else 1
                return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def parts_of(claims):
    out = []
    for pid in ("P527", "P361"):
        for cl in claims.get(pid, []):
            snak = cl.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue
            qid = (snak.get("datavalue", {}).get("value", {}) or {}).get("id")
            if qid:
                out.append(qid)
    return out


async def ensure_location(conn, city, cc, now, expires):
    return await conn.fetchval(
        """INSERT INTO scraped_locations
             (id, source, source_id, name, country_alpha2, scraped_at, expires_at)
           VALUES ($1,'location_resolver',$2,$3,$4,$5,$6)
           ON CONFLICT (source, source_id) DO UPDATE
             SET scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
           RETURNING id""",
        uuid.uuid4(), f"{cc}:{city}", city, cc, now, expires)


async def upsert(conn, *, source, source_id, name, kind, starts_at, ends_at,
                 loc_id, qid, raw, now, expires, stats):
    if source not in stats:
        stats[source] = {"added": 0, "updated": 0, "errors": 0}
    dedupe_year = starts_at.year if starts_at else None
    try:
        inserted = await conn.fetchval(
            """INSERT INTO scraped_events
                 (id, source, source_id, name, kind, interest_key, starts_at,
                  ends_at, location_id, wikidata_qid, raw, scraped_at,
                  expires_at, dedupe_year)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14)
               ON CONFLICT (source, source_id, dedupe_year) DO UPDATE
                 SET name=EXCLUDED.name, kind=EXCLUDED.kind,
                     starts_at=EXCLUDED.starts_at, ends_at=EXCLUDED.ends_at,
                     location_id=EXCLUDED.location_id, raw=EXCLUDED.raw,
                     scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
               RETURNING (xmax = 0)""",
            uuid.uuid4(), source[:32], source_id[:128], name[:512],
            (kind or "event")[:64], "city-sweep", starts_at, ends_at, loc_id,
            (qid or "")[:32], json.dumps(raw)[:4000], now, expires, dedupe_year)
        stats[source]["added" if inserted else "updated"] += 1
    except Exception as exc:  # noqa: BLE001
        stats[source]["errors"] += 1
        print(f"    row failed ({name[:40]}): {type(exc).__name__}", flush=True)


def kind_of(claims):
    for cl in claims.get("P31", []):
        cid = (cl.get("mainsnak", {}).get("datavalue", {}).get("value", {})
               or {}).get("id")
        if cid and cid != "Q5":
            return cid.lower()
    return "event"


async def process_item(conn, qid, city, cc, loc_id, start_d, end_d,
                       now, expires, stats, report, seen, depth=0):
    """Recursively resolve an item or its editions into dated rows."""
    if qid in seen or depth > 3:
        return
    seen.add(qid)
    ent = polite(get_entity, qid)
    claims = ent.get("claims", {})
    label = ent.get("labels", {}).get("en", {}).get("value") or qid
    s, e = wiki_date(claims, ["P580", "P585"]), wiki_date(claims, ["P582"])
    if s:
        d = date.fromisoformat(s)
        rec = {"qid": qid, "name": label, "start": s, "end": e,
               "url": f"https://www.wikidata.org/wiki/{qid}",
               "city": city, "search": None}
        if start_d <= d <= end_d:
            await upsert(conn, source="wikidata", source_id=qid, name=label,
                         kind=kind_of(claims), starts_at=d,
                         ends_at=date.fromisoformat(e) if e else None,
                         loc_id=loc_id, qid=qid,
                         raw={"source_url": rec["url"], "city": city,
                              "country": cc, "sweep": "pass3b-series"},
                         now=now, expires=expires, stats=stats)
            report[city]["persisted"].append(rec)
            print(f"  [{city}] persisted {label} ({s})", flush=True)
        else:
            report[city]["outside_window"].append(rec)
        return
    # undated series -> follow has-part / part-of to editions
    for child in parts_of(claims)[:12]:
        await process_item(conn, child, city, cc, loc_id, start_d, end_d,
                           now, expires, stats, report, seen, depth + 1)


async def main():
    t0 = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)
    stats: dict = {}
    report: dict = {}
    seen: set = set()

    try:
        locs = {}
        city_triples = set(SERIES.values())
        for city, (cc, city_qid, _terms) in TERMS.items():
            city_triples.add((city, cc, city_qid))
        for city, cc, city_qid in city_triples:
            locs[city] = await ensure_location(conn, city, cc, now, expires)
        # 1) resolve undated series via editions
        for qid, (city, cc, _cq) in SERIES.items():
            report.setdefault(city, {"persisted": [], "outside_window": [],
                                     "undated": []})
            await process_item(conn, qid, city, cc, locs[city], start_d,
                               end_d, now, expires, stats, report, seen)
        # 2) retried/new curated terms for Madrid & Milan
        for city, (cc, city_qid, terms) in TERMS.items():
            report.setdefault(city, {"persisted": [], "outside_window": [],
                                     "undated": []})
            for term in terms:
                try:
                    hits = polite(search_entities, term)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] search '{term}' failed after retries: "
                          f"{type(exc).__name__}", flush=True)
                    continue
                for hit in hits[:4]:
                    qid = hit.get("id")
                    if qid:
                        await process_item(conn, qid, city, cc, locs[city],
                                           start_d, end_d, now, expires,
                                           stats, report, seen)
        finished = now_utc()
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CityEventSweep3b',$3,$4,$5,$6,$7,$8,$9)""",
                uuid.uuid4(), src, t0, finished, "success",
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)",
                int((finished - t0).total_seconds() * 1000))
        status = "success"
    finally:
        await conn.close()

    print(json.dumps({"status": status, "by_source": stats,
                      "cities": report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
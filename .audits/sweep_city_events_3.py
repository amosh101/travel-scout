#!/usr/bin/env python3
"""Pass 3: targeted fill for the three empty cities (Geneva, Madrid, Milan)
plus a curated top-up for Amsterdam.

Method (all real HTTP, no fabrication):
  1. wbsearchentities on curated recurring-event names per city.
  2. wbgetentities to pull P580 (start) / P585 (point in time) / P582 (end)
     and P31 (instance-of) labels from Wikidata claims ONLY.
  3. Rows dated inside the 150-day window are persisted with the same
     upsert shape as passes 1-2 (source='wikidata', keyed on QID).
  4. Items dated outside the window are reported, not persisted.

Run inside the api container:
    docker cp .audits/sweep_city_events_3.py <api>:/tmp/
    docker exec -w /app -e PYTHONPATH=/app <api> python /tmp/sweep_city_events_3.py
"""

import asyncio
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg
from curl_cffi import requests as cffi_requests

try:
    from app.config import get_settings
except ImportError:  # pragma: no cover
    from app.settings import get_settings

UA = "travel-scout-city-sweep/3.0 (github.com/amosh101/travel-scout)"
API = "https://www.wikidata.org/w/api.php"

CITIES = {
    "Amsterdam": ("NL", "Q727", [
        "Amsterdam Light Festival",
        "Amsterdam Christmas market",
        "Mooi Weer Sportloop",
    ]),
    "Geneva": ("CH", "Q71", [
        "Course de l'Escalade",
        "Geneva International Film Festival",
        "Geneva Christmas market",
        "Fete de l'Escalade",
    ]),
    "Madrid": ("ES", "Q2807", [
        "Jazz Madrid",
        "Madrid Christmas market",
        "Madrid Jazz Festival",
        "Navidad Madrid",
    ]),
    "Milan": ("IT", "Q490", [
        "Oh Bej! Oh Bej!",
        "Milan Christmas market",
        "Milano Film Festival",
    ]),
}
WINDOW_DAYS = 150


def now_utc():
    return datetime.now(timezone.utc)


def _wiki_date(claims, props):
    """First best-rank date among the given prop ids, as YYYY-MM-DD or None."""
    for pid in props:
        for cl in claims.get(pid, []):
            snak = cl.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue
            raw = snak.get("datavalue", {}).get("value", {})
            t = raw.get("time", "")
            m = re.match(r"[+-](\d{4})-(\d{2})-(\d{2})", t)
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


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
    source_key = source[:32]
    if source_key not in stats:
        stats[source_key] = {"added": 0, "updated": 0, "errors": 0}
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
            uuid.uuid4(), source_key, source_id[:128], name[:512],
            (kind or "event")[:64], "city-sweep", starts_at, ends_at, loc_id,
            (qid or "")[:32], json.dumps(raw)[:4000], now, expires, dedupe_year)
        stats[source_key]["added" if inserted else "updated"] += 1
    except Exception as exc:  # noqa: BLE001
        stats[source_key]["errors"] += 1
        print(f"    row failed ({name[:40]}): {type(exc).__name__}", flush=True)


async def main():
    t0 = datetime.now(timezone.utc)
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)
    stats: dict = {}
    report: dict = {}
    seen_qids: set = set()

    try:
        for city, (cc, city_qid, terms) in CITIES.items():
            item = report.setdefault(city, {"cc": cc, "persisted": [],
                                            "outside_window": [],
                                            "undated": [], "dead_qids": []})
            loc_id = await ensure_location(conn, city, cc, now, expires)
            for term in terms:
                try:
                    hits = search_entities(term)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] search '{term}' failed: {type(exc).__name__}",
                          flush=True)
                    continue
                got_any = False
                for hit in hits[:4]:
                    qid = hit.get("id")
                    if not qid or qid in seen_qids:
                        continue
                    seen_qids.add(qid)
                    got_any = True
                    try:
                        ent = get_entity(qid)
                    except Exception as exc:  # noqa: BLE001
                        item["dead_qids"].append({"qid": qid,
                                                  "why": type(exc).__name__})
                        continue
                    claims = ent.get("claims", {})
                    label = (ent.get("labels", {}).get("en", {})
                             .get("value") or hit.get("label", qid))
                    s = _wiki_date(claims, ["P580", "P585"])
                    e = _wiki_date(claims, ["P582"])
                    is_human = False
                    # quick instance-of probe: skip persons
                    p31 = claims.get("P31", [])
                    for cl in p31:
                        v = (cl.get("mainsnak", {}).get("datavalue", {})
                             .get("value", {}) or {})
                        if v.get("id") == "Q5":
                            is_human = True
                    if is_human:
                        continue
                    if not s:
                        item["undated"].append({"qid": qid, "name": label,
                                                "search": term})
                        continue
                    d = date.fromisoformat(s)
                    rec = {"qid": qid, "name": label, "search": term,
                           "start": s, "end": e,
                           "url": f"https://www.wikidata.org/wiki/{qid}"}
                    if not (start_d <= d <= end_d):
                        item["outside_window"].append(rec)
                        continue
                    kind = "event"
                    for cl in p31:
                        cid = (cl.get("mainsnak", {}).get("datavalue", {})
                               .get("value", {}) or {}).get("id")
                        if cid:
                            kind = "item_" + cid.lower()
                            break
                    await upsert(conn, source="wikidata", source_id=qid,
                                 name=label, kind=kind,
                                 starts_at=d, ends_at=date.fromisoformat(e)
                                 if e else None,
                                 loc_id=loc_id, qid=qid,
                                 raw={"source_url": rec["url"], "city": city,
                                      "country": cc, "sweep": "pass3-curated",
                                      "search": term},
                                 now=now, expires=expires, stats=stats)
                    item["persisted"].append(rec)
                    print(f"  [{city}] persisted {label} ({s})", flush=True)
                if not got_any:
                    item["undated"].append({"search": term, "name": None})
        finished = now_utc()
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CityEventSweep3',$3,$4,$5,$6,$7,$8,$9)""",
                uuid.uuid4(), src, t0, finished, "success",
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)",
                int((finished - t0).total_seconds() * 1000))
        status = "success"
    except Exception as exc:  # noqa: BLE001
        status = f"error {type(exc).__name__}: {exc}"
        print(status, flush=True)
    finally:
        await conn.close()

    print(json.dumps({"status": status, "by_source": stats,
                      "cities": report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
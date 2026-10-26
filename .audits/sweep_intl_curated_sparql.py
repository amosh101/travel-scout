#!/usr/bin/env python3
"""Pass 4d: curated marquee events via SPARQL ONLY (no api.php).

Per (city, term):
  q1: EntitySearch(term) in SPARQL + P580/P585/P582 dates + P31 label.
      Dated-in-window -> persist. Undated -> q2 editions:
      { ?ed (P361|P179) item } / { item P527 ?ed } with dates.
Nothing outside the window is persisted; it is reported instead.
Receipts: scraper CityEventSweepIntl-Curated-SPARQL.
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

UA = "travel-scout-city-sweep/4.5 (github.com/amosh101/travel-scout)"
URL = "https://query.wikidata.org/sparql"
SLEEP_S = 2.0

CITIES = {
    "Dubai": ("AE", "asia", ["Dubai Marathon", "Dubai Shopping Festival",
                             "Dubai World Cup"]),
    "Abu Dhabi": ("AE", "asia", ["Abu Dhabi Grand Prix",
                                 "Abu Dhabi Marathon"]),
    "Singapore": ("SG", "asia", ["Standard Chartered Singapore Marathon"]),
    "Tokyo": ("JP", "asia", ["Tokyo Marathon"]),
    "Bangkok": ("TH", "asia", ["Bangkok Marathon"]),
    "Hong Kong": ("HK", "asia", ["Hong Kong Marathon", "Hong Kong Sevens",
                                 "Hong Kong Arts Festival"]),
    "Shanghai": ("CN", "asia", ["Shanghai Marathon"]),
    "Seoul": ("KR", "asia", ["Seoul Marathon"]),
    "Cape Town": ("ZA", "africa", ["Cape Town Cycle Tour",
                                   "Cape Town International Jazz Festival"]),
    "Johannesburg": ("ZA", "africa", ["Johannesburg Marathon"]),
    "Maputo": ("MZ", "africa", ["AZGO Festival", "Maputo Marathon"]),
    "Marrakech": ("MA", "africa", ["Marrakech Marathon"]),
    "Cairo": ("EG", "africa", ["Cairo Marathon"]),
    "Nairobi": ("KE", "africa", ["Nairobi Marathon"]),
    "Vienna": ("AT", "europe", ["Vienna City Marathon",
                                "Wiener Christkindlmarkt"]),
    "Berlin": ("DE", "europe", ["JazzFest Berlin"]),
    "Munich": ("DE", "europe", ["Oktoberfest"]),
    "Lisbon": ("PT", "europe", ["Lisbon Marathon", "Web Summit"]),
    "Prague": ("CZ", "europe", ["Prague Marathon", "Prague Christmas Market"]),
    "Athens": ("GR", "europe", ["Athens Marathon"]),
    "Copenhagen": ("DK", "europe", ["Copenhagen Marathon"]),
    "Budapest": ("HU", "europe", ["Budapest Marathon"]),
}
WINDOW_DAYS = 150
PER_TERM_LIMIT = 6


def now_utc():
    return datetime.now(timezone.utc)


def polite(fn, *a, **kw):
    for attempt in (1, 2, 3):
        try:
            time.sleep(SLEEP_S)
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                raise
            wait = 8 * attempt
            print(f"    retry {attempt} after {type(exc).__name__} "
                  f"(sleep {wait}s)", flush=True)
            time.sleep(wait)


def sparql_run(q: str, timeout_s: int = 40):
    r = cffi_requests.get(
        URL, params={"query": q, "format": "json"},
        headers={"User-Agent": UA, "Accept": "application/sparql-results+json"},
        impersonate="chrome120", timeout=timeout_s)
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def term_query(term: str) -> str:
    tl = json.dumps(term)
    return f"""
SELECT ?item ?itemLabel ?start ?end WHERE {{
  Service wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                    wikibase:api "EntitySearch" ;
                    mwapi:search {tl} ;
                    mwapi:language "en" ;
                    mwapi:limit "{PER_TERM_LIMIT}" .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  ?item wdt:P31 ?cls .
  OPTIONAL {{ ?item wdt:P580 ?s0 }}
  OPTIONAL {{ ?item wdt:P585 ?s1 }}
  OPTIONAL {{ ?item wdt:P582 ?end }}
  BIND(COALESCE(?s0, ?s1) AS ?start)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 20"""


def editions_query(item: str) -> str:
    return f"""
SELECT ?item ?itemLabel ?start ?end WHERE {{
  {{ ?item (wdt:P361|wdt:P179) wd:{item} . }}
  UNION
  {{ wd:{item} wdt:P527 ?item . }}
  ?item (wdt:P580|wdt:P585) ?start .
  OPTIONAL {{ ?item wdt:P582 ?end }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 40"""


def parse(rows):
    out, undated = [], []
    for b in rows:
        try:
            qid = re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
            start = (b.get("start", {}).get("value") or "")[:10]
            m = re.match(r"\d{4}-\d{2}-\d{2}", start)
            y, mo, d = (int(x) for x in start.split("-")) if m else (0, 0, 0)
            if not m or mo == 0:
                if qid not in undated:
                    undated.append(qid)
                continue
            start = f"{y:04d}-{mo:02d}-{d if d >= 1 else 1:02d}"
            end = b["end"]["value"][:10] if b.get("end") else None
            out.append({"qid": qid,
                        "name": b.get("itemLabel", {}).get("value", qid),
                        "start": start, "end": end})
        except (KeyError, AttributeError):
            continue
    return out, undated


async def ensure_location(conn, city, cc, now, expires):
    return await conn.fetchval(
        """INSERT INTO scraped_locations
             (id, source, source_id, name, country_alpha2, scraped_at,
              expires_at)
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
            (qid or "")[:32], json.dumps(raw)[:4000], now, expires,
            dedupe_year)
        stats[source]["added" if inserted else "updated"] += 1
    except Exception as exc:  # noqa: BLE001
        stats[source]["errors"] += 1
        print(f"    row failed ({name[:40]}): {type(exc).__name__}",
              flush=True)


async def main():
    t0 = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://",
                                        "postgresql://")
    conn = await asyncpg.connect(dsn)
    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)
    stats: dict = {}
    seen: set = set()

    try:
        for city, (cc, region, terms) in CITIES.items():
            loc_id = await ensure_location(conn, city, cc, now, expires)
            for term in terms:
                try:
                    rows, undated = parse(polite(sparql_run,
                                                 term_query(term)))
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}/{term}] SPARQL failed: "
                          f"{type(exc).__name__}", flush=True)
                    continue
                # editions follow-up for undated series (bounded)
                if undated:
                    for uq in undated[:3]:
                        if uq in seen:
                            continue
                        seen.add(uq)
                        try:
                            ed = parse(polite(sparql_run,
                                              editions_query(uq)))
                        except Exception as exc:  # noqa: BLE001
                            print(f"  [{city}/{term}] editions {uq} failed: "
                                  f"{type(exc).__name__}", flush=True)
                            ed = []
                        rows.extend(ed[0])
                for rec in rows:
                    if rec["qid"] in seen:
                        continue
                    seen.add(rec["qid"])
                    d = date.fromisoformat(rec["start"])
                    if not (start_d <= d <= end_d):
                        continue
                    await upsert(
                        conn, source="wikidata", source_id=rec["qid"],
                        name=rec["name"], kind="event", starts_at=d,
                        ends_at=date.fromisoformat(rec["end"])
                        if rec["end"] else None,
                        loc_id=loc_id, qid=rec["qid"],
                        raw={"source_url":
                             f"https://www.wikidata.org/wiki/{rec['qid']}",
                             "city": city, "country": cc,
                             "region": region,
                             "sweep": "pass4d-curated-sparql",
                             "search": term},
                        now=now, expires=expires, stats=stats)
                    print(f"  [{city}] persisted {rec['name']} "
                          f"({rec['start']}) via '{term}'", flush=True)
        finished = now_utc()
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CityEventSweepIntl-Curated-SPARQL',$3,$4,
                           'success',$5,$6,$7,$8)""",
                uuid.uuid4(), src, t0, finished, s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)",
                int((finished - t0).total_seconds() * 1000))
        status = "success"
    finally:
        await conn.close()

    print(json.dumps({"status": status, "by_source": stats}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
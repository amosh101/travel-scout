#!/usr/bin/env python3
"""Pass 4b: SPARQL legs for the intl cities, using city QIDs verified via a
batched Wikidata label+city-class resolution (see sweep_intl_events log).
Article legs already ran in the main intl sweep; this adds the Wikidata legs.

Same upsert shape. Receipts under scraper CityEventSweepIntl-SPARQL.
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

UA = "travel-scout-city-sweep/4.2 (github.com/amosh101/travel-scout)"
SPARQL_URL = "https://query.wikidata.org/sparql"

CITY_QIDS = {
    "Maputo": "Q3889", "Johannesburg": "Q34647", "Cape Town": "Q5465",
    "Marrakech": "Q101625", "Cairo": "Q85", "Nairobi": "Q3870",
    "Vienna": "Q1741", "Berlin": "Q64", "Munich": "Q1726", "Lisbon": "Q597",
    "Prague": "Q1085", "Athens": "Q1524", "Copenhagen": "Q1748",
    "Budapest": "Q1781", "Dubai": "Q612", "Abu Dhabi": "Q1519",
    "Singapore": "Q334", "Tokyo": "Q1490", "Bangkok": "Q1861",
    "Hong Kong": "Q8646", "Shanghai": "Q8686", "Seoul": "Q8684",
}
CC = {"Maputo": "MZ", "Johannesburg": "ZA", "Cape Town": "ZA",
      "Marrakech": "MA", "Cairo": "EG", "Nairobi": "KE", "Vienna": "AT",
      "Berlin": "DE", "Munich": "DE", "Lisbon": "PT", "Prague": "CZ",
      "Athens": "GR", "Copenhagen": "DK", "Budapest": "HU", "Dubai": "AE",
      "Abu Dhabi": "AE", "Singapore": "SG", "Tokyo": "JP", "Bangkok": "TH",
      "Hong Kong": "HK", "Shanghai": "CN", "Seoul": "KR"}
REGIONS = {"Maputo": "africa", "Johannesburg": "africa", "Cape Town": "africa",
           "Marrakech": "africa", "Cairo": "africa", "Nairobi": "africa",
           "Vienna": "europe", "Berlin": "europe", "Munich": "europe",
           "Lisbon": "europe", "Prague": "europe", "Athens": "europe",
           "Copenhagen": "europe", "Budapest": "europe", "Dubai": "asia",
           "Abu Dhabi": "asia", "Singapore": "asia", "Tokyo": "asia",
           "Bangkok": "asia", "Hong Kong": "asia", "Shanghai": "asia",
           "Seoul": "asia"}
ROOTS = ("wd:Q132241 wd:Q40244 wd:Q464980 wd:Q47454 wd:Q220753 "
         "wd:Q47345468 wd:Q7571069 wd:Q6554922")
WINDOW_DAYS = 150
SPARQL_TIMEOUT_S = 15


def now_utc():
    return datetime.now(timezone.utc)


def sparql(qid: str, start_d, end_d, deep: bool) -> str:
    loc = (f"""{{ ?item wdt:P131* wd:{qid} }}
  UNION
  {{ ?item wdt:P276/wdt:P131* wd:{qid} }}""" if deep else
           f"""{{ ?item wdt:P131 wd:{qid} }}
  UNION
  {{ ?item wdt:P276 wd:{qid} }}""")
    return f"""
SELECT ?item ?itemLabel ?classLabel ?start ?end WHERE {{
  VALUES ?root {{ {ROOTS} }}
  ?item wdt:P31/wdt:P279* ?root .
  {loc}
  ?item (wdt:P580|wdt:P585) ?start .
  FILTER(?start >= "{start_d.isoformat()}T00:00:00Z"^^xsd:dateTime
      && ?start <= "{end_d.isoformat()}T23:59:59Z"^^xsd:dateTime)
  OPTIONAL {{ ?item (wdt:P582|wdt:P5826) ?end }}
  ?item wdt:P31 ?cls .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?start LIMIT 40"""


def run_sparql(qid, start_d, end_d, timeout_s, deep=True):
    r = cffi_requests.get(
        SPARQL_URL,
        params={"query": sparql(qid, start_d, end_d, deep), "format": "json"},
        headers={"User-Agent": UA,
                 "Accept": "application/sparql-results+json"},
        impersonate="chrome120", timeout=timeout_s)
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def parse_bindings(bindings):
    out = []
    for b in bindings:
        try:
            qid = re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
            start = b["start"]["value"][:10]
            if not re.match(r"\d{4}-\d{2}-\d{2}$", start):
                continue
            y, m, d = (int(x) for x in start.split("-"))
            if m == 0:
                continue
            start = f"{y:04d}-{m:02d}-{d if d >= 1 else 1:02d}"
            end = b["end"]["value"][:10] if b.get("end") else None
            out.append({
                "qid": qid,
                "name": b.get("itemLabel", {}).get("value", qid),
                "kind": (b.get("classLabel", {}).get("value", "event")
                         .lower().replace(" ", "_")),
                "start": start, "end": end})
        except (KeyError, AttributeError):
            continue
    return out


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


async def upsert_row(conn, *, source, source_id, name, kind, interest_key,
                     starts_at, ends_at, loc_id, qid, raw, now, expires,
                     stats):
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
            (kind or "event")[:64], (interest_key or "city-sweep")[:64],
            starts_at, ends_at, loc_id, (qid or "")[:32],
            json.dumps(raw)[:4000], now, expires, dedupe_year)
        stats[source]["added" if inserted else "updated"] += 1
    except Exception as exc:  # noqa: BLE001
        stats[source]["errors"] += 1
        print(f"    row failed ({source} {name[:40]}): {type(exc).__name__}",
              flush=True)


async def main():
    started_at = datetime.now(timezone.utc)
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://",
                                        "postgresql://")
    conn = await asyncpg.connect(dsn)
    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)
    stats: dict = {}
    report: dict = {}

    try:
        for city, qid in CITY_QIDS.items():
            item = report.setdefault(city, {"events": [], "sparql_mode":
                                            "failed"})
            loc_id = await ensure_location(conn, city, CC[city], now, expires)
            rows, mode = [], "failed"
            try:
                rows = parse_bindings(run_sparql(qid, start_d, end_d,
                                                 SPARQL_TIMEOUT_S, deep=True))
                mode = "deep"
            except Exception as exc:  # noqa: BLE001
                print(f"  [{city}] deep {type(exc).__name__}", flush=True)
            if not rows:
                try:
                    rows = parse_bindings(run_sparql(qid, start_d, end_d,
                                                     SPARQL_TIMEOUT_S,
                                                     deep=False))
                    mode = "simple"
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] simple {type(exc).__name__}",
                          flush=True)
            item["sparql_mode"] = mode
            for e in rows:
                await upsert_row(
                    conn, source="wikidata", source_id=e["qid"],
                    name=e["name"], kind=e["kind"],
                    interest_key="city-sweep",
                    starts_at=date.fromisoformat(e["start"]),
                    ends_at=date.fromisoformat(e["end"]) if e["end"] else None,
                    loc_id=loc_id, qid=e["qid"],
                    raw={"source_url":
                         f"https://www.wikidata.org/wiki/{e['qid']}",
                         "city": city, "country": CC[city],
                         "region": REGIONS[city], "sweep": "pass4b-sparql"},
                    now=now, expires=expires, stats=stats)
                item["events"].append({"name": e["name"][:90],
                                       "date": e["start"], "end": e["end"],
                                       "url": f"https://www.wikidata.org/wiki/{e['qid']}"})
            print(f"  [{city}] {len(item['events'])} wikidata event(s), "
                  f"mode={mode}", flush=True)
        finished_at = datetime.now(timezone.utc)
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CityEventSweepIntl-SPARQL',$3,$4,'success',
                           $5,$6,$7,$8)""",
                uuid.uuid4(), src, started_at, finished_at,
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)",
                int((finished_at - started_at).total_seconds() * 1000))
        status = "success"
    finally:
        await conn.close()

    print(json.dumps({"status": status, "by_source": stats,
                      "cities": report}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
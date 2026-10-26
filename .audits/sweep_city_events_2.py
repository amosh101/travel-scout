#!/usr/bin/env python3
"""Sweep pass 2: wider noun set + wider Wikidata root classes.

Adds: theatre, comedy, literature, nightlife, football, cycling, sailing,
golf, beer article legs; SPARQL roots for fashion weeks (Q47454), film
festival editions (Q220753), tennis editions (Q47345468), theatre (Q7571069),
Christmas markets (Q6554922). Idempotent upserts on the same ledger.
Holidays re-fetched for the report only (not persisted).
"""

import asyncio
import json
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg
from curl_cffi import requests as cffi_requests

try:
    from app.config import get_settings
except ImportError:  # pragma: no cover
    from app.settings import get_settings

from app.clients.free_events import build_free_event_aggregator
from app.clients.holidays import build_holidays_client

USER_AGENT = "travel-scout-city-sweep/1.0 (github.com/amosh101/travel-scout)"
SPARQL_URL = "https://query.wikidata.org/sparql"

CITIES = {
    "Amsterdam": ("NL", "Q727"),
    "Barcelona": ("ES", "Q1492"),
    "Florence": ("IT", "Q2044"),
    "Geneva": ("CH", "Q71"),
    "London": ("GB", "Q84"),
    "Madrid": ("ES", "Q2807"),
    "Milan": ("IT", "Q490"),
    "Paris": ("FR", "Q90"),
    "Rome": ("IT", "Q220"),
    "Zurich": ("CH", "Q72"),
}
AP_KEYS = ["theatre", "comedy", "literature", "nightlife", "football",
           "cycling", "sailing", "golf", "beer"]
ROOTS = ("wd:Q132241 wd:Q40244 wd:Q464980 wd:Q47454 wd:Q220753 "
         "wd:Q47345468 wd:Q7571069 wd:Q6554922")
WINDOW_DAYS = 150
PER_APP_TIMEOUT_S = 25
SPARQL_TIMEOUT_S = 15
TOTAL_BUDGET_S = 460


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
}} ORDER BY ?start LIMIT 60"""


def run_sparql(qid, start_d, end_d, timeout_s, deep=True):
    r = cffi_requests.get(
        SPARQL_URL,
        params={"query": sparql(qid, start_d, end_d, deep), "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        impersonate="chrome120", timeout=timeout_s,
    )
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def parse_bindings(bindings):
    import re as _re
    out = []
    for b in bindings:
        try:
            qid = _re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
            out.append({
                "qid": qid,
                "name": b.get("itemLabel", {}).get("value", qid),
                "kind": (b.get("classLabel", {}).get("value", "event")
                          .lower().replace(" ", "_")),
                "start": b["start"]["value"][:10],
                "end": b["end"]["value"][:10] if b.get("end") else None,
            })
        except (KeyError, AttributeError):
            continue
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


async def upsert_row(conn, *, source, source_id, name, kind, interest_key,
                     starts_at, ends_at, loc_id, qid, raw, now, expires, stats):
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
            uuid.uuid4(), source, source_id[:128], name[:512], (kind or "event")[:64],
            (interest_key or "city-sweep")[:64], starts_at, ends_at, loc_id,
            (qid or "")[:32], json.dumps(raw)[:4000], now, expires, dedupe_year)
        stats[source]["added" if inserted else "updated"] += 1
    except Exception as exc:  # noqa: BLE001
        stats[source]["errors"] += 1
        print(f"    row failed ({name[:40]}): {type(exc).__name__}", flush=True)


async def main():
    t0 = time.time()
    started_at = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)

    agg = build_free_event_aggregator()
    wp = agg.wikipedia
    stats: dict[str, dict] = {}
    report: dict[str, dict] = {}
    partial = False

    try:
        for city, (cc, qid) in CITIES.items():
            if time.time() - t0 > TOTAL_BUDGET_S:
                partial = True
                print(f"TIME BUDGET reached — stopping at {city}", flush=True)
                break
            item = report.setdefault(city, {"cc": cc, "events": [], "sparql_mode": "failed"})
            loc_id = await ensure_location(conn, city, cc, now, expires)

            for key in AP_KEYS:
                try:
                    recs = await asyncio.wait_for(
                        wp.search_city_articles(key, city=city, country_alpha2=cc,
                                                start_date=start_d, end_date=end_d,
                                                limit=8),
                        timeout=PER_APP_TIMEOUT_S)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}/{key}] article leg {type(exc).__name__}", flush=True)
                    continue
                for r in recs or []:
                    note = (r.extra or {}).get("date_note")
                    await upsert_row(
                        conn, source=r.source or "wikipedia",
                        source_id=(r.source_qid or f"{(r.name or '').lower()}|{city}|"
                                   f"{r.starts_at.isoformat() if r.starts_at else 'nodate'}"),
                        name=r.name or "", kind=r.kind or "event", interest_key=key,
                        starts_at=r.starts_at, ends_at=r.ends_at, loc_id=loc_id,
                        qid=r.source_qid or "", now=now, expires=expires, stats=stats,
                        raw={"source_url": r.source_url, "city": city, "country": cc,
                             "date_note": note} | (r.extra or {}))
                    item["events"].append({"name": r.name[:90], "date": r.starts_at.isoformat()
                                           if r.starts_at else None, "note": note,
                                           "url": r.source_url})

            mode, rows = "failed", []
            try:
                rows = parse_bindings(run_sparql(qid, start_d, end_d, SPARQL_TIMEOUT_S, deep=True))
                mode = "deep"
            except Exception as exc:  # noqa: BLE001
                print(f"  [{city}] deep SPARQL {type(exc).__name__}", flush=True)
            if not rows:
                try:
                    rows = parse_bindings(run_sparql(qid, start_d, end_d, SPARQL_TIMEOUT_S, deep=False))
                    mode = "simple"
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] simple SPARQL {type(exc).__name__}", flush=True)
            item["sparql_mode"] = mode
            for e in rows:
                await upsert_row(
                    conn, source="wikidata", source_id=e["qid"], name=e["name"],
                    kind=e["kind"], interest_key="city-sweep",
                    starts_at=date.fromisoformat(e["start"]),
                    ends_at=date.fromisoformat(e["end"]) if e["end"] else None,
                    loc_id=loc_id, qid=e["qid"], stats=stats,
                    raw={"source_url": f"https://www.wikidata.org/wiki/{e['qid']}",
                         "city": city, "country": cc, "sweep": f"roots-{mode}"},
                    now=now, expires=expires)
                item["events"].append({"name": e["name"][:90], "date": e["start"],
                                       "note": None,
                                       "url": f"https://www.wikidata.org/wiki/{e['qid']}"})
            print(f"  [{city}] pass2: {len(item['events'])} new leg event(s), sparql={mode}",
                  flush=True)

        # holidays for the report (not persisted)
        hol = {}
        hc = build_holidays_client()
        for ccode in sorted({v[0] for v in CITIES.values()}):
            got = []
            for year in (start_d.year, start_d.year + 1):
                try:
                    phs = await asyncio.wait_for(hc.fetch_year(year, ccode), timeout=20)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [holidays {ccode}/{year}] {type(exc).__name__}", flush=True)
                    phs = []
                for ph in phs or []:
                    d = date.fromisoformat(str(ph.date)[:10])
                    if start_d <= d <= end_d:
                        got.append({"date": d.isoformat(),
                                    "name": ph.local_name or ph.english_name})
            hol[ccode] = sorted(got, key=lambda h: h["date"])
    finally:
        finished_at = now_utc()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = "partial" if partial else "success"
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CityEventSweep2',$3,$4,$5,$6,$7,$8,$9)""",
                uuid.uuid4(), src, started_at, finished_at, status,
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)", duration_ms)
        await conn.close()

    print(json.dumps({"status": status, "duration_ms": duration_ms,
                      "by_source": stats, "new_legs": report, "holidays": hol}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
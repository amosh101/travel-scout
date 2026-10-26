#!/usr/bin/env python3
"""City-scoped event sweep: guarantee a future-dated event list for every
catalog city, independent of the product leg's 4s SPARQL cap.

Run inside the api container:
    docker cp .audits/sweep_city_events.py <api>:/tmp/
    docker exec -w /app -e PYTHONPATH=/app <api> python /tmp/sweep_city_events.py

Legs per city:
  1. app's WikipediaListClient.search_city_articles for 6 solid nouns
  2. DIRECT city-scoped Wikidata SPARQL (deep P131* UNION P276/P131*,
     20s; falls back to a simple one-hop query on failure)
  3. Nager.Date holidays for the country, window-filtered (report only)

Persists legs 1-2 into scraped_events/scraped_locations with runs receipts.
Writes nothing to user tables.
"""

import asyncio
import hashlib
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
AP_KEYS = ["film", "fashion", "opera", "marathon", "electronic-music", "food-wine"]
WINDOW_DAYS = 150
PER_APP_TIMEOUT_S = 25
SPARQL_TIMEOUT_S = 20
TOTAL_BUDGET_S = 470


def now_utc():
    return datetime.now(timezone.utc)


def make_source_id(qid_or_name: str, city: str, d) -> str:
    sid = qid_or_name or f"{(qname := qid_or_name)}|{city}"  # noqa: F841
    if len(sid) > 128:
        sid = hashlib.sha1(sid.encode()).hexdigest()[:32]
    return sid


async def ensure_location(conn, city, cc, now, expires):
    return await conn.fetchval(
        """
        INSERT INTO scraped_locations
          (id, source, source_id, name, country_alpha2, scraped_at, expires_at)
        VALUES ($1,'location_resolver',$2,$3,$4,$5,$6)
        ON CONFLICT (source, source_id) DO UPDATE
          SET scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
        RETURNING id
        """,
        uuid.uuid4(), f"{cc}:{city}", city, cc, now, expires,
    )


async def upsert_row(conn, *, source, source_id, name, kind, interest_key,
                     starts_at, ends_at, loc_id, qid, raw, now, expires, stats):
    if source not in stats:
        stats[source] = {"added": 0, "updated": 0, "errors": 0}
    dedupe_year = starts_at.year if starts_at else None
    try:
        inserted = await conn.fetchval(
            """
            INSERT INTO scraped_events
              (id, source, source_id, name, kind, interest_key, starts_at, ends_at,
               location_id, wikidata_qid, raw, scraped_at, expires_at, dedupe_year)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,$14)
            ON CONFLICT (source, source_id, dedupe_year) DO UPDATE
              SET name=EXCLUDED.name, kind=EXCLUDED.kind,
                  starts_at=EXCLUDED.starts_at, ends_at=EXCLUDED.ends_at,
                  location_id=EXCLUDED.location_id, raw=EXCLUDED.raw,
                  scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
            RETURNING (xmax = 0)
            """,
            uuid.uuid4(), source[:32].encode().decode(), source_id[:128], name[:512],
            (kind or "event")[:64], (interest_key or "city-sweep")[:64],
            starts_at, ends_at, loc_id, (qid or "")[:32], json.dumps(raw)[:4000],
            now, expires, dedupe_year,
        )
        stats[source]["added" if inserted else "updated"] += 1
    except Exception as exc:  # noqa: BLE001
        stats[source]["errors"] += 1
        print(f"    row failed ({source} {name[:40]}): {type(exc).__name__}", flush=True)


def _q(v: str) -> str:
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def sparql_deep(qid: str, start_d: date, end_d: date) -> str:
    return f"""
SELECT ?item ?itemLabel ?classLabel ?start ?end WHERE {{
  VALUES ?root {{ wd:Q132241 wd:Q40244 wd:Q464980 }}
  ?item wdt:P31/wdt:P279* ?root .
  {{ ?item wdt:P131* wd:{qid} }}
  UNION
  {{ ?item wdt:P276/wdt:P131* wd:{qid} }}
  ?item (wdt:P580|wdt:P585) ?start .
  FILTER(?start >= "{start_d.isoformat()}T00:00:00Z"^^xsd:dateTime
      && ?start <= "{end_d.isoformat()}T23:59:59Z"^^xsd:dateTime)
  OPTIONAL {{ ?item (wdt:P582|wdt:P5826) ?end }}
  ?item wdt:P31 ?cls .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?start LIMIT 60"""


def sparql_simple(qid: str, start_d: date, end_d: date) -> str:
    return f"""
SELECT ?item ?itemLabel ?classLabel ?start ?end WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q132241 .
  {{ ?item wdt:P131 wd:{qid} }}
  UNION
  {{ ?item wdt:P276 wd:{qid} }}
  ?item (wdt:P580|wdt:P585) ?start .
  FILTER(?start >= "{start_d.isoformat()}T00:00:00Z"^^xsd:dateTime
      && ?start <= "{end_d.isoformat()}T23:59:59Z"^^xsd:dateTime)
  OPTIONAL {{ ?item (wdt:P582|wdt:P5826) ?end }}
  ?item wdt:P31 ?cls .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?start LIMIT 60"""


def run_sparql(qid: str, start_d: date, end_d: date, timeout_s: int) -> list[dict]:
    r = cffi_requests.get(
        SPARQL_URL,
        params={"query": sparql_deep(qid, start_d, end_d), "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        impersonate="chrome120", timeout=timeout_s,
    )
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def parse_bindings(bindings: list[dict], city: str) -> list[dict]:
    out = []
    for b in bindings:
        try:
            uri = b["item"]["value"]
            qid = re.search(r"(Q\d+)$", uri).group(1)
            start_val = b["start"]["value"][:10]
            out.append({
                "qid": qid,
                "name": b.get("itemLabel", {}).get("value", qid),
                "kind": (b.get("classLabel", {}).get("value", "event")
                          .lower().replace(" ", "_")),
                "start": start_val,
                "end": b["end"]["value"][:10] if b.get("end") else None,
            })
        except (KeyError, AttributeError):
            continue
    return out


async def main() -> None:
    t0 = time.time()
    started_at = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)

    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)

    agg = build_free_event_aggregator()
    holidays_client = build_holidays_client()
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
            item = report.setdefault(city, {"cc": cc, "events": [], "app_hits": {}, "sparql_mode": "failed"})
            loc_id = await ensure_location(conn, city, cc, now, expires)

            # Leg 1: article search (product leg)
            for key in AP_KEYS:
                try:
                    recs = await asyncio.wait_for(
                        wp.search_city_articles(key, city=city, country_alpha2=cc,
                                                start_date=start_d, end_date=end_d, limit=8),
                        timeout=PER_APP_TIMEOUT_S,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}/{key}] article leg error: {type(exc).__name__}", flush=True)
                    continue
                if recs:
                    item["app_hits"][key] = len(recs)
                for r in recs if recs else []:
                    note = (r.extra or {}).get("date_note")
                    await upsert_row(
                        conn, source=r.source or "wikipedia",
                        source_id=(r.source_qid or f"{(r.name or '').lower()}|{city}|"
                                   f"{r.starts_at.isoformat() if r.starts_at else 'nodate'}"),
                        name=r.name or "", kind=r.kind or "music_festival",
                        interest_key=key, starts_at=r.starts_at, ends_at=r.ends_at,
                        loc_id=loc_id, qid=r.source_qid or "",
                        raw={"source_url": r.source_url, "city": city, "country": cc,
                             "date_note": note} | (r.extra or {}),
                        now=now, expires=expires, stats=stats,
                    )
                    item["events"].append({"name": r.name[:90], "date": _q(r.starts_at),
                                           "end": _q(r.ends_at), "class": r.kind,
                                           "source": "wikipedia", "note": note,
                                           "url": r.source_url})

            # Leg 2: direct city-scoped SPARQL
            mode, rows = "failed", []
            for mode, qfn, tmo in (("deep", None, SPARQL_TIMEOUT_S),):
                try:
                    rows = parse_bindings(run_sparql(qid, start_d, end_d, tmo), city)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] deep SPARQL {type(exc).__name__}", flush=True)
                    rows = []
            if not rows:
                try:
                    rows = parse_bindings(
                        run_sparql_simple_ok(qid, start_d, end_d, SPARQL_TIMEOUT_S), city)
                    mode, rows_used = "simple", rows
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] simple SPARQL {type(exc).__name__}", flush=True)
                    mode = "failed"
            else:
                mode, rows_used = "deep", rows
            item["sparql_mode"] = mode
            for e in rows:
                await upsert_row(
                    conn, source="wikidata", source_id=e["qid"],
                    name=e["name"], kind=e["kind"], interest_key="city-sweep",
                    starts_at=date.fromisoformat(e["start"]),
                    ends_at=date.fromisoformat(e["end"]) if e["end"] else None,
                    loc_id=loc_id, qid=e["qid"],
                    raw={"source_url": f"https://www.wikidata.org/wiki/{e['qid']}",
                         "city": city, "country": cc, "sweep": mode},
                    now=now, expires=expires, stats=stats,
                )
                item["events"].append({"name": e["name"][:90], "date": e["start"],
                                       "end": e["end"], "class": e["kind"],
                                       "source": "wikidata", "note": None,
                                       "url": f"https://www.wikidata.org/wiki/{e['qid']}"})
            print(f"  [{city}] done: {len(item['events'])} event(s) "
                  f"(sparql={mode})", flush=True)

        # Leg 3: holidays per country (report only, not persisted)
        hol_report = {}
        for cc in sorted({v[0] for v in CITIES.values()}):
            hols = []
            for year in (start_d.year, start_d.year + 1):
                try:
                    phs = await asyncio.wait_for(
                        holidays_client.fetch_year(year, cc), timeout=20)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [holidays {cc}/{year}] {type(exc).__name__}", flush=True)
                    phs = []
                for ph in phs or []:
                    d = date.fromisoformat(str(ph.date)[:10])
                    if start_d <= d <= end_d:
                        hols.append({"date": d.isoformat(),
                                     "name": ph.local_name or ph.english_name})
            hol_report[cc] = sorted(hols, key=lambda h: h["date"])
    finally:
        finished_at = now_utc()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = "partial" if partial else "success"
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CityEventSweep',$3,$4,$5,$6,$7,$8,$9)""",
                uuid.uuid4(), src[:32].encode().decode(), started_at, finished_at, status,
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)", duration_ms,
            )
        await conn.close()

    print(json.dumps({"status": status, "duration_ms": duration_ms,
                      "by_source": stats, "cities": report, "holidays": hol_report},
                     indent=2))


def run_sparql_simple_ok(qid, start_d, end_d, timeout_s):
    r = cffi_requests.get(
        SPARQL_URL,
        params={"query": sparql_simple(qid, start_d, end_d), "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        impersonate="chrome120", timeout=timeout_s,
    )
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


if __name__ == "__main__":
    asyncio.run(main())
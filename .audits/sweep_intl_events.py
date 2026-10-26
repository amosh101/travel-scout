#!/usr/bin/env python3
"""International city event sweep: Africa, Europe (beyond the catalog 10), Asia.

For each city:
  Leg A: city-scoped Wikidata SPARQL, city QID resolved IN-QUERY via
         EntitySearch (mwapi) + city-class filter -- no api.php, no 429s.
         Deep (P131*) first, simple (one-hop) fallback.
  Leg B: product article leg via build_free_event_aggregator().wikipedia
         for 8 solid interest keys.
  Leg C: holidays report per country (not persisted).

Same upsert shape as passes 1-3. Receipts per source. Idempotent.
Run inside the api container:
    docker cp .audits/sweep_intl_events.py <api>:/tmp/
    docker exec -w /app -e PYTHONPATH=/app <api> python /tmp/sweep_intl_events.py
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

from app.clients.free_events import build_free_event_aggregator
from app.clients.holidays import build_holidays_client

UA = "travel-scout-city-sweep/4.0 (github.com/amosh101/travel-scout)"
SPARQL_URL = "https://query.wikidata.org/sparql"

# city -> (country_alpha2, region)
CITIES = {
    # Africa
    "Maputo": ("MZ", "africa"),
    "Johannesburg": ("ZA", "africa"),
    "Cape Town": ("ZA", "africa"),
    "Marrakech": ("MA", "africa"),
    "Cairo": ("EG", "africa"),
    "Nairobi": ("KE", "africa"),
    # Europe (beyond the catalog 10)
    "Vienna": ("AT", "europe"),
    "Berlin": ("DE", "europe"),
    "Munich": ("DE", "europe"),
    "Lisbon": ("PT", "europe"),
    "Prague": ("CZ", "europe"),
    "Athens": ("GR", "europe"),
    "Copenhagen": ("DK", "europe"),
    "Budapest": ("HU", "europe"),
    # Asia incl. Middle East
    "Dubai": ("AE", "asia"),
    "Abu Dhabi": ("AE", "asia"),
    "Singapore": ("SG", "asia"),
    "Tokyo": ("JP", "asia"),
    "Bangkok": ("TH", "asia"),
    "Hong Kong": ("HK", "asia"),
    "Shanghai": ("CN", "asia"),
    "Seoul": ("KR", "asia"),
}
ARTICLE_KEYS = ["film", "fashion", "marathon", "electronic-music",
                "food-wine", "theatre", "jazz", "opera"]
ROOTS = ("wd:Q132241 wd:Q40244 wd:Q464980 wd:Q47454 wd:Q220753 "
         "wd:Q47345468 wd:Q7571069 wd:Q6554922")
WINDOW_DAYS = 150
SPARQL_TIMEOUT_S = 18
PER_ARTICLE_TIMEOUT_S = 20
TOTAL_BUDGET_S = 520


def now_utc():
    return datetime.now(timezone.utc)


def resolve_city_qid(city, timeout_s=15):
    """EntitySearch on api.php (polite pace) -> first hit that is a city
    (instance-of chain incl. Q515 / Q5119) else None."""
    import time as _t
    for attempt in (1, 2, 3):
        try:
            _t.sleep(1.2)
            r = cffi_requests.get(
                "https://www.wikidata.org/w/api.php",
                params={"action": "wbsearchentities", "search": city,
                        "language": "en", "format": "json", "type": "item",
                        "limit": "5"},
                headers={"User-Agent": UA}, impersonate="chrome120",
                timeout=timeout_s)
            r.raise_for_status()
            for hit in r.json().get("search", []):
                qid = hit.get("id")
                if not qid:
                    continue
                _t.sleep(1.2)
                d = cffi_requests.get(
                    "https://www.wikidata.org/w/api.php",
                    params={"action": "wbgetentities", "ids": qid,
                            "props": "claims", "format": "json"},
                    headers={"User-Agent": UA}, impersonate="chrome120",
                    timeout=timeout_s)
                d.raise_for_status()
                p31 = [((cl.get("mainsnak", {})
                             .get("datavalue", {}).get("value", {}) or {})
                        .get("id"))
                       for cl in d.json().get("entities", {})
                       .get(qid, {}).get("claims", {}).get("P31", [])]
                if "Q515" in p31 or "Q5119" in p31:
                    return qid
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"    resolve {city} try {attempt}: {type(exc).__name__}",
                  flush=True)
    return None


CITY_QIDS: dict = {}


def _sparql(qid_expr: str, start_d, end_d, deep: bool) -> str:
    loc = (f"""{{ ?item wdt:P131* {qid_expr} }}
  UNION
  {{ ?item wdt:P276/wdt:P131* {qid_expr} }}""" if deep else
           f"""{{ ?item wdt:P131 {qid_expr} }}
  UNION
  {{ ?item wdt:P276 {qid_expr} }}""")
    return f"""
SELECT ?item ?itemLabel ?classLabel ?start ?end WHERE {{
  VALUES ?cityQ {{ {qid_expr} }}
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


def run_sparql(city, start_d, end_d, timeout_s, deep=True):
    qid = CITY_QIDS.get(city)
    if not qid:
        return []
    r = cffi_requests.get(
        SPARQL_URL,
        params={"query": _sparql(f"wd:{qid}", start_d, end_d, deep),
                "format": "json"},
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


async def ensure_location(conn, city, cc, region, now, expires):
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
                     stats, region):
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
    t0 = time.time()
    started_at = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://",
                                        "postgresql://")
    conn = await asyncpg.connect(dsn)

    start_d = date.today()
    end_d = start_d + timedelta(days=WINDOW_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)

    agg = build_free_event_aggregator()
    wp = agg.wikipedia
    hc = build_holidays_client()
    stats: dict = {}
    report: dict = {}
    partial = False

    try:
        for city in CITIES:
            CITY_QIDS[city] = resolve_city_qid(city)
            print(f"  [qid] {city} -> {CITY_QIDS[city] or 'UNRESOLVED'}",
                  flush=True)
        for city, (cc, region) in CITIES.items():
            if time.time() - t0 > TOTAL_BUDGET_S:
                partial = True
                print(f"TIME BUDGET — stopping at {city}", flush=True)
                break
            item = report.setdefault(city, {"cc": cc, "region": region,
                                            "events": [], "sparql_mode": "failed"})
            loc_id = await ensure_location(conn, city, cc, region, now, expires)

            # Leg A: city-scoped SPARQL (mwapi-resolved city QID)
            rows, mode = [], "failed"
            try:
                rows = parse_bindings(run_sparql(city, start_d, end_d,
                                                 SPARQL_TIMEOUT_S, deep=True))
                mode = "deep"
            except Exception as exc:  # noqa: BLE001
                print(f"  [{city}] deep SPARQL {type(exc).__name__}",
                      flush=True)
            if not rows:
                try:
                    rows = parse_bindings(run_sparql(city, start_d, end_d,
                                                     SPARQL_TIMEOUT_S,
                                                     deep=False))
                    mode = "simple"
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}] simple SPARQL {type(exc).__name__}",
                          flush=True)
            item["sparql_mode"] = mode
            for e in rows:
                await upsert_row(conn, source="wikidata", source_id=e["qid"],
                                 name=e["name"], kind=e["kind"],
                                 interest_key="city-sweep",
                                 starts_at=date.fromisoformat(e["start"]),
                                 ends_at=date.fromisoformat(e["end"])
                                 if e["end"] else None,
                                 loc_id=loc_id, qid=e["qid"],
                                 raw={"source_url":
                                      f"https://www.wikidata.org/wiki/{e['qid']}",
                                      "city": city, "country": cc,
                                      "region": region, "sweep": mode},
                                 now=now, expires=expires, stats=stats,
                                 region=region)
                item["events"].append({"name": e["name"][:90],
                                       "date": e["start"], "end": e["end"],
                                       "source": "wikidata",
                                       "url": f"https://www.wikidata.org/wiki/{e['qid']}"})

            # Leg B: product article legs
            for key in ARTICLE_KEYS:
                try:
                    recs = await asyncio.wait_for(
                        wp.search_city_articles(key, city=city,
                                                country_alpha2=cc,
                                                start_date=start_d,
                                                end_date=end_d, limit=8),
                        timeout=PER_ARTICLE_TIMEOUT_S)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [{city}/{key}] article {type(exc).__name__}",
                          flush=True)
                    continue
                for r in recs or []:
                    note = (r.extra or {}).get("date_note")
                    source = r.source or "wikipedia"
                    sid = r.source_qid or (
                        f"{(r.name or '').lower()}|{city}|"
                        f"{r.starts_at.isoformat() if r.starts_at else 'nodate'}")
                    await upsert_row(conn, source=source, source_id=sid,
                                     name=r.name or "",
                                     kind=r.kind or "event", interest_key=key,
                                     starts_at=r.starts_at, ends_at=r.ends_at,
                                     loc_id=loc_id, qid=r.source_qid or "",
                                     raw={"source_url": r.source_url,
                                          "city": city, "country": cc,
                                          "region": region,
                                          "date_note": note} | (r.extra or {}),
                                     now=now, expires=expires, stats=stats,
                                     region=region)
                    item["events"].append({"name": (r.name or "")[:90],
                                           "date": r.starts_at.isoformat()
                                           if r.starts_at else None,
                                           "end": r.ends_at.isoformat()
                                           if r.ends_at else None,
                                           "source": source, "note": note,
                                           "url": r.source_url})
            item["events"] = item["events"][:12]
            print(f"  [{city}] done: {len(item['events'])} event leg(s), "
                  f"sparql={mode}", flush=True)

        # Leg C: holidays (report only)
        hol = {}
        for cc in sorted({v[0] for v in CITIES.values()}):
            got = []
            for year in (start_d.year, start_d.year + 1):
                try:
                    phs = await asyncio.wait_for(hc.fetch_year(year, cc),
                                                 timeout=20)
                except Exception as exc:  # noqa: BLE001
                    print(f"  [holidays {cc}/{year}] {type(exc).__name__}",
                          flush=True)
                    phs = []
                for ph in phs or []:
                    d = date.fromisoformat(str(ph.date)[:10])
                    if start_d <= d <= end_d:
                        got.append({"date": d.isoformat(),
                                    "name": ph.local_name or ph.english_name})
            hol[cc] = sorted(got, key=lambda h: h["date"])[:12]
    finally:
        finished_at = now_utc()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = "partial" if partial else "success"
        for src, s in sorted(stats.items()):
            try:
                await conn.execute(
                    """INSERT INTO scraped_runs
                         (id, source, scraper, started_at, finished_at, status,
                          added, updated, error, duration_ms)
                       VALUES ($1,$2,'CityEventSweepIntl',$3,$4,$5,$6,$7,$8,$9)""",
                    uuid.uuid4(), src, started_at, finished_at, status,
                    s["added"], s["updated"],
                    None if not s["errors"] else f"{s['errors']} row error(s)",
                    duration_ms)
            except Exception:  # noqa: BLE001
                pass
        try:
            final = json.dumps({"status": status,
                                "duration_ms": duration_ms,
                                "by_source": stats,
                                "cities": report, "holidays": hol}, indent=2)
            with open("/tmp/sweep_intl_report.json", "w") as f:
                f.write(final)
            print(final[:800], flush=True)
            print("FULL-SAVED /tmp/sweep_intl_report.json", flush=True)
        except Exception as exc:  # noqa: BLE001  # noqa: BLE001
            print(f"report dump failed: {exc}", flush=True)
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
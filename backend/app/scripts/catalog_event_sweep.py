"""Catalog-wide event sweep: every destination, every wired source class.

Runs against the LIVE `destinations` table (city additions need no code
change). Legs per city, in priority order:

  W  Wikipedia article search over the full 33-noun interest map
     (paced 0.8s + one 429-retry — burst = 429, empirically proven).
  S  Wikidata SPARQL, city QID resolved in ONE batched query
     (label + ISO-3166 alpha-2 via P17/P300 + city-class filter),
     widened event roots (music/wine/beer/food/exhibitions/esports...),
     deep-then-simple fallback.
  V  Wikivoyage Events/Festivals sections: only conservatively parseable
     recurring rules ('third weekend in May', '28-29 November 2026'),
     computed to the next occurrence. Precision noted per row.

Idempotent upserts on (source, source_id, dedupe_year); per-source
receipts into scraped_runs; JSON summary to stdout. Designed for the
daily no-agent cron; safe to re-run at any point (partial runs resume).

Usage inside the api container:
    docker exec -w /app -e PYTHONPATH=/app <api> \
        python -m app.scripts.catalog_event_sweep
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
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

logger = logging.getLogger(__name__)

UA = "travel-scout-catalog-sweep/1.0 (github.com/amosh101/travel-scout)"
SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"

ARTICLE_KEYS = [
    "jazz", "electronic-music", "film", "art-museums", "theatre", "opera",
    "architecture", "design", "fashion", "photography", "food-wine", "wine",
    "coffee", "caviar", "adventure", "skiing", "marathon", "golf",
    "cycling", "sailing", "esports", "nightlife", "wellness", "football",
]
ARTICLE_PACE_S = 0.8
SPARQL_TIMEOUT_S = 15
SPARQL_PACE_S = 4.0
WINDOWS_DAYS = 150
TOTAL_BUDGET_S = 700
PER_ARTICLE_TIMEOUT_S = 12
ARTICLE_WORKERS = 4  # thread pool; the client blocks internally on
                     # sync HTTP, threads are the only true parallelism

WIDE_ROOTS = (
    "wd:Q132241 wd:Q40244 wd:Q464980 wd:Q47454 wd:Q220753 wd:Q47345468 "
    "wd:Q7571069 wd:Q6554922 wd:Q868557 wd:Q462100 wd:Q2919327 "
    "wd:Q131398 wd:Q500633 wd:Q57598 wd:Q21003903")

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6,
            "weekend": 5, "weekdays": 4}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "last": -1}
MONTHS = ["january", "february", "march", "april", "may", "june",
          "july", "august", "september", "october", "november", "december"]


def now_utc():
    return datetime.now(timezone.utc)


def month_n(v: str) -> int:
    v = v.strip().lower()[:3]
    try:
        return MONTHS.index(v) + 1
    except ValueError:
        return 0


# --------------------------- city QID resolution --------------------------
CITY_QID_CACHE = "/tmp/catalog_sweep_city_qids.json"


def city_qid_batch(cities: list[tuple[str, str]], timeout_s: int = 60):
    """Two-phase resolution (Blazegraph returns 0 rows if P17/P300 joins
    ride on a label-VALUES query):
      A) label + city-class -> candidate QIDs per label
      B) VALUES ?item batch -> P17/P300 ISO-2 per candidate.
    Country-code match decides. Falls back to a /tmp cache file."""
    try:
        with open(CITY_QID_CACHE) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    missed = [f"{n}|{cc}" for n, cc in cities
              if f"{n}|{cc}" not in cache]
    if missed:
        labels = [k.rsplit("|", 1)[0] for k in missed]
        want_cc = {k.rsplit("|", 1)[0]: k.rsplit("|", 1)[1]
                   for k in missed}
        vals = " ".join(f'"{l}"@en' for l in sorted(set(labels)))
        qa = f"""
SELECT ?item ?lbl WHERE {{
  VALUES ?lbl {{ {vals} }}
  ?item rdfs:label ?lbl .
  {{ ?item wdt:P31/wdt:P279* wd:Q515 . }}
  UNION
  {{ ?item wdt:P31 wd:Q5119 . }}
}} LIMIT 300
"""
        r = cffi_requests.get(
            SPARQL_URL, params={"query": qa, "format": "json"},
            headers={"User-Agent": UA,
                     "Accept": "application/sparql-results+json"},
            impersonate="chrome120", timeout=timeout_s)
        r.raise_for_status()
        candidates: dict[str, set[str]] = {}
        for b in r.json().get("results", {}).get("bindings", []):
            try:
                lbl = b["lbl"]["value"]
                qid = re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
                if lbl in want_cc:
                    candidates.setdefault(lbl, set()).add(qid)
            except (KeyError, AttributeError, TypeError):
                continue
        if candidates:
            items = " ".join(f"wd:{q}"
                             for qs in candidates.values() for q in sorted(qs))
            qb = f"""
SELECT ?item ?iso2 WHERE {{
  VALUES ?item {{ {items} }}
  ?item wdt:P17 ?c .
  ?c wdt:P297 ?iso2 .
}} LIMIT 500
"""
            r = cffi_requests.get(
                SPARQL_URL, params={"query": qb, "format": "json"},
                headers={"User-Agent": UA,
                         "Accept": "application/sparql-results+json"},
                impersonate="chrome120", timeout=timeout_s)
            r.raise_for_status()
            iso_of: dict[str, str] = {}
            for b in r.json().get("results", {}).get("bindings", []):
                try:
                    qid = re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
                    iso_of[qid] = b["iso2"]["value"].upper()
                except (KeyError, AttributeError, TypeError):
                    continue
            for label, qs in candidates.items():
                cc_key = want_cc[label]  # store with the caller's exact case
                cc = cc_key.upper()
                for qid in sorted(qs):
                    if iso_of.get(qid) == cc:
                        cache[f"{label}|{cc_key}"] = qid
                        break
        with open(CITY_QID_CACHE, "w") as f:
            json.dump(cache, f)
    out = {}
    for n, cc in cities:
        out[f"{n}|{cc}"] = cache.get(f"{n}|{cc}")
    return out


# ----------------------------- Wikidata legs ------------------------------
def sparql_wide(qid: str, start_d: date, end_d: date, deep: bool) -> str:
    loc = (f"""{{ ?item wdt:P131* wd:{qid} }}
  UNION
  {{ ?item wdt:P276/wdt:P131* wd:{qid} }}""" if deep else
           f"""{{ ?item wdt:P131 wd:{qid} }}
  UNION
  {{ ?item wdt:P276 wd:{qid} }}""")
    return f"""
SELECT ?item ?itemLabel ?classLabel ?start ?end WHERE {{
  VALUES ?root {{ {WIDE_ROOTS} }}
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
        params={"query": sparql_wide(qid, start_d, end_d, deep),
                "format": "json"},
        headers={"User-Agent": UA,
                 "Accept": "application/sparql-results+json"},
        impersonate="chrome120", timeout=timeout_s)
    r.raise_for_status()
    return r.json().get("results", {}).get("bindings", [])


def parse_sparql_rows(bindings):
    out = []
    for b in bindings:
        try:
            qid = re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
            start = b["start"]["value"][:10]
            m = re.match(r"\d{4}-\d{2}-\d{2}", start)
            if not m:
                continue
            y, mo, d = (int(x) for x in start.split("-"))
            if mo == 0:
                continue
            start = f"{y:04d}-{mo:02d}-{d if d >= 1 else 1:02d}"
            end = b["end"]["value"][:10] if b.get("end") else None
            out.append({"qid": qid,
                        "name": b.get("itemLabel", {}).get("value", qid),
                        "kind": (b.get("classLabel", {}).get("value", "event")
                                 .lower().replace(" ", "_")),
                        "start": start, "end": end})
        except (KeyError, AttributeError):
            continue
    return out


# -------------------------- Wikivoyage events leg -------------------------
def wikivoyage_events_wikitext(city: str) -> list[str]:
    """Sections named Events/Festivals, as wikitext (one API call each)."""
    r = cffi_requests.get(
        WIKIVOYAGE_API,
        params={"action": "parse", "page": city, "prop": "sections",
                "format": "json"},
        headers={"User-Agent": UA}, impersonate="chrome120", timeout=25)
    r.raise_for_status()
    secs = [s for s in r.json().get("parse", {}).get("sections", [])
            if s.get("anchor", "").lower() in
            ("events", "events_and_festivals", "festivals", "do")]
    out = []
    for s in secs[:2]:
        r2 = cffi_requests.get(
            WIKIVOYAGE_API,
            params={"action": "parse", "page": city, "prop": "wikitext",
                    "section": s["index"], "format": "json"},
            headers={"User-Agent": UA}, impersonate="chrome120", timeout=25)
        r2.raise_for_status()
        out.append(r2.json()["parse"]["wikitext"]["*"][:20000])
    return out


def _nth_weekday(year: int, month: int, which: int, weekday: int) -> date:
    first = date(year, month, 1)
    first_wd = first.weekday()
    if which == -1:  # last
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        last = nxt - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    delta = (weekday - first_wd) % 7
    return first + timedelta(days=delta + 7 * (which - 1))


def parse_recurring_rules(text: str, today: date, horizon: date):
    """Conservative, bullet-aware: carries the event NAME from the wiki
    bullet ('* '''Sumida fireworks''' ... third Saturday in July').
    Yields (name, start, end, note, precision)."""
    rows = []
    bullets = re.split(r"\n\s*[*#]+\s*", text)
    base_year = today.year
    for bullet in bullets:
        if not bullet.strip():
            continue
        flat = re.sub(r"\s+", " ", bullet)
        name_m = re.search(r"'''([^']{3,80})'''", flat) or \
            re.search(r"\[\[([^\]|]{3,80})(?:\|[^\]]*)?\]\]", flat) or \
            re.search(r"\{\{\s*do\s*\|\s*name=([^|]{3,80})", flat)
        name = (name_m.group(1).strip() if name_m else "")[:110]
        # ordinal weekday rules ("third weekend in May")
        for m in re.finditer(
                r"(first|second|third|fourth|fifth|last)\s+"
                r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                r"weekend)\s+in\s+([A-Za-z]+)", flat, re.I):
            which, wd, mon = m.group(1).lower(), m.group(2).lower(), m.group(3)
            mn = month_n(mon)
            if not mn:
                continue
            for yr in (base_year, base_year + 1):
                d = _nth_weekday(yr, mn, ORDINALS[which], WEEKDAYS[wd])
                if today <= d <= horizon:
                    if not name:
                        continue
                    rows.append((name, d, d,
                                 f"wikivoyage rule: '{m.group(0)}'; "
                                 + ("weekend = Sat-Sun"
                                    if wd == "weekend" else "recurring"),
                                 "day-rule"))
                    break
        # dated range with year
        for m in re.finditer(
                r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\s*[-–—]\s*"
                r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", flat):
            mn1, mn2 = month_n(m.group(2)), month_n(m.group(5))
            if not (mn1 and mn2 and name):
                continue
            s = date(int(m.group(3)), mn1, int(m.group(1)))
            e = date(int(m.group(6)), mn2, int(m.group(4)))
            if today <= s <= horizon:
                rows.append((name, s, e,
                             "wikivoyage listing (dated range)", "day-range"))
                break
        # single explicit date
        for m in re.finditer(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", flat):
            mn = month_n(m.group(2))
            if not (mn and name):
                continue
            d = date(int(m.group(3)), mn, int(m.group(1)))
            if today <= d <= horizon:
                rows.append((name, d, d, "wikivoyage listing (dated)",
                             "day"))
                break
    return rows[:6]


# ------------------------------- persistence ------------------------------
async def ensure_location(conn, name, cc, now, expires):
    return await conn.fetchval(
        """INSERT INTO scraped_locations
             (id, source, source_id, name, country_alpha2, scraped_at,
              expires_at)
           VALUES ($1,'location_resolver',$2,$3,$4,$5,$6)
           ON CONFLICT (source, source_id) DO UPDATE
             SET scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
           RETURNING id""",
        uuid.uuid4(), f"{cc}:{name}", name, cc, now, expires)


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
        logger.warning("row failed (%s %s): %s", source, name[:40],
                       type(exc).__name__)


# --------------------------------- main -----------------------------------
async def main() -> dict:
    t0 = time.time()
    started_at = now_utc()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://",
                                        "postgresql://")
    conn = await asyncpg.connect(dsn)
    today = date.today()
    horizon = today + timedelta(days=WINDOWS_DAYS)
    now, expires = now_utc(), now_utc() + timedelta(days=30)

    aggregate = build_free_event_aggregator()
    wp = aggregate.wikipedia
    stats: dict = {}
    report: dict = {}
    partial = False

    try:
        dests = await conn.fetch(
            """SELECT d.name AS name, d.country AS country, d.region AS region,
                      d.iata_code AS iata_code
                 FROM destinations d
                 LEFT JOIN LATERAL (
                    SELECT min(l.scraped_at) AS last_sweep
                      FROM scraped_locations l
                     WHERE l.source = 'location_resolver'
                       AND l.source_id = (SELECT c.alpha2 || ':' || d.name
                                            FROM countries c
                                           WHERE c.name = d.country
                                             LIMIT 1)
                ) ls ON true
                ORDER BY coalesce(ls.last_sweep, 'epoch'), d.name""")
        countries = await conn.fetch("SELECT alpha2, name FROM countries")
        full2iso = {c["name"].lower(): c["alpha2"] for c in countries}
        cities = []
        for r in dests:
            iso = full2iso.get((r["country"] or "").lower())
            if iso:
                cities.append((r["name"], iso))
        qids = city_qid_batch(cities)
        iso_by_name = {n: cc for n, cc in cities}

        for r in dests:
            if time.time() - t0 > TOTAL_BUDGET_S:
                partial = True
                logger.warning("TIME BUDGET — stopping at %s", r["name"])
                break
            city, region = r["name"], r["region"] or "europe"
            cc = iso_by_name.get(city)
            if not cc:
                continue
            item = report.setdefault(
                city, {"cc": cc, "region": region, "counts": {},
                       "legs": ""})
            loc_id = await ensure_location(conn, city, cc, now, expires)

            # Leg S: wikidata wide roots
            qid = qids.get(f"{city}|{cc}")
            mode, srows = "failed", []
            if qid:
                try:
                    srows = parse_sparql_rows(run_sparql(
                        qid, today, horizon, SPARQL_TIMEOUT_S, deep=True))
                    mode = "deep"
                except Exception:  # noqa: BLE001
                    pass
                if not srows:
                    try:
                        srows = parse_sparql_rows(run_sparql(
                            qid, today, horizon, SPARQL_TIMEOUT_S,
                            deep=False))
                        mode = "simple" if srows else mode
                    except Exception:  # noqa: BLE001
                        pass
                n = 0
                for e in srows:
                    await upsert_row(
                        conn, source="wikidata", source_id=e["qid"],
                        name=e["name"], kind=e["kind"],
                        interest_key="city-sweep",
                        starts_at=date.fromisoformat(e["start"]),
                        ends_at=date.fromisoformat(e["end"])
                        if e["end"] else None,
                        loc_id=loc_id, qid=e["qid"],
                        raw={"source_url":
                             f"https://www.wikidata.org/wiki/{e['qid']}",
                             "city": city, "country": cc, "region": region,
                             "sweep": f"catalog-wide-{mode}"},
                        now=now, expires=expires, stats=stats)
                    n += 1
                item["counts"]["wikidata"] = n
                time.sleep(SPARQL_PACE_S)

            # Leg W: wikipedia article legs over the full noun map
            # (thread-pooled; each task owns its event loop because the
            # product client blocks internally)
            def _one_key(key_: str):
                return key_, asyncio.run(_article_search(key_))

            async def _article_search(key_: str):
                return await asyncio.wait_for(
                    wp.search_city_articles(
                        key_, city=city, country_alpha2=cc,
                        start_date=today, end_date=horizon, limit=8),
                    timeout=PER_ARTICLE_TIMEOUT_S)

            wcount = 0
            from concurrent.futures import (  # noqa: E402
                ThreadPoolExecutor, as_completed)
            collected: dict = {}
            with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
                futures = {pool.submit(_one_key, k): k
                           for k in ARTICLE_KEYS}
                for fut in as_completed(futures, timeout=420):
                    try:
                        key, recs = fut.result()
                    except Exception:  # noqa: BLE001
                        continue
                    collected[key] = recs or []
            for key in ARTICLE_KEYS:
                for rec in collected.get(key, []):
                    # real-data guards (wikipedia leg only):
                    # 1) event-word in title (kills city pages, people,
                    #    unrelated articles placed via infobox location)
                    # 2) title carries a year outside the window years
                    #    (kills other-edition articles, e.g. 2025 cups)
                    # 3) parsed start predates today (kills the
                    #    month-placeholder drift into the past)
                    title = rec.name or ""
                    if not re.search(
                            r"festival|marathon|cup|rally|exhibition|"
                            r"concert|biennale|market|\bfair\b|summit|"
                            r"gala|series|parade|fashion week|fringe|"
                            r"competition|tournament|\brace\b|"
                            r"event|regatta|\bopen\b|week\b",
                            title, re.I):
                        continue
                    title_year = re.search(r"\b(19\d\d|20\d\d)\b", title)
                    if title_year and title_year.group(1) not in (
                            str(today.year), str(today.year + 1)):
                        continue
                    if rec.starts_at and rec.starts_at < today:
                        continue
                    note = (rec.extra or {}).get("date_note")
                    source = rec.source or "wikipedia"
                    sid = rec.source_qid or (
                        f"{(rec.name or '').lower()}|{city}|"
                        f"{rec.starts_at.isoformat() if rec.starts_at else 'nodate'}")
                    await upsert_row(
                        conn, source=source, source_id=sid,
                        name=rec.name or "", kind=rec.kind or "event",
                        interest_key=key, starts_at=rec.starts_at,
                        ends_at=rec.ends_at, loc_id=loc_id,
                        qid=rec.source_qid or "",
                        raw={"source_url": rec.source_url, "city": city,
                             "country": cc, "region": region,
                             "date_note": note} | (rec.extra or {}),
                        now=now, expires=expires, stats=stats)
                    wcount += 1
            item["counts"]["wikipedia"] = wcount

            # Leg V: wikivoyage recurring rules
            vcount = 0
            try:
                wikitexts = wikivoyage_events_wikitext(city)
            except Exception:  # noqa: BLE001
                wikitexts = []
            for wt in wikitexts:
                rules = parse_recurring_rules(wt, today, horizon)
                for name, s_, e_, note, prec in rules:
                    rule_hash = f"{s_.isoformat()}|{note[:48]}"
                    await upsert_row(
                        conn, source="wikivoyage",
                        source_id=f"{city}|{rule_hash}",
                        name=name, kind="event", interest_key="city-sweep",
                        starts_at=s_, ends_at=e_,
                        loc_id=loc_id, qid="", raw={
                            "source_url":
                            f"https://en.wikivoyage.org/wiki/{city}",
                            "city": city, "country": cc, "region": region,
                            "date_note": note, "precision": prec,
                            "sweep": "catalog-wide"},
                        now=now, expires=expires, stats=stats)
                    vcount += 1
                time.sleep(1.0)
            item["counts"]["wikivoyage"] = vcount
            item["legs"] = f"wikidata_mode={mode if qid else 'unresolved'}"

        finished_at = now_utc()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = "partial" if partial else "success"
        for src, s in sorted(stats.items()):
            await conn.execute(
                """INSERT INTO scraped_runs
                     (id, source, scraper, started_at, finished_at, status,
                      added, updated, error, duration_ms)
                   VALUES ($1,$2,'CatalogEventSweep',$3,$4,$5,$6,$7,$8,$9)""",
                uuid.uuid4(), src, started_at, finished_at, status,
                s["added"], s["updated"],
                None if not s["errors"] else f"{s['errors']} row error(s)",
                duration_ms)
        return {"status": status, "duration_ms": duration_ms,
                "by_source": stats, "cities": report}
    finally:
        try:
            await conn.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), indent=2, default=str))
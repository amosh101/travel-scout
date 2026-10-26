"""Official-site marquee scraper: registry-driven, real HTTP, no static dates.

Each registry entry is a marquee event whose official site publishes its
next edition's dates. Every run re-fetches the page and re-extracts the
window with a site-tuned regex (verified 2026-10-26 against the live
page). If the site's phrasing changes, the entry reports ``no_match``
and the ledger row simply decays at ``expires_at`` — silently stale rows
are structurally impossible to create fresh.

Usage (inside the api container):
    docker exec -w /app -e PYTHONPATH=/app <api> python -m app.scripts.official_marquee

Writes to scraped_locations / scraped_events (idempotent upserts keyed on
(source, source_id, dedupe_year)) and appends receipts to scraped_runs
(source='official-site', scraper='OfficialMarquee').
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
from curl_cffi import requests

from app.config import get_settings

logger = logging.getLogger("official_marquee")

UA = "travel-scout-marquee/1.0 (github.com/amosh101/travel-scout)"
WINDOW_DAYS = 150
FETCH_TIMEOUT_S = 25

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month(v: str) -> int | None:
    return MONTHS.get(v.strip()[:3].lower())


def _full_full(text: str, pattern: str) -> tuple[date, date | None] | None:
    """'13 November 2026 - 6 January 2027' style."""
    m = re.search(pattern, text, re.I | re.S)
    if not (m and m.group(1) and m.group(2) and m.group(3)
            and m.group(4) and m.group(5) and m.group(6)):
        return None
    mo1, mo2 = _month(m.group(2)), _month(m.group(5))
    if not mo1 or not mo2:
        return None
    start = date(int(m.group(3)), mo1, int(m.group(1)))
    end = date(int(m.group(6)), mo2, int(m.group(4)))
    return start, end


def _single_or_range(text: str, pattern: str) -> tuple[date, date | None] | None:
    """'January 17, 2027' / 'November 28-29, 2026' / '14 Mar 2027'."""
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    y = m.groupdict().get("year")
    mo = _month(m.groupdict().get("mon") or "")
    if not y or not mo:
        return None
    d1 = int(m.groupdict().get("d1"))
    d2 = m.groupdict().get("d2")
    start = date(int(y), mo, d1)
    end = date(int(y), mo, int(d2)) if d2 else None
    if end and end < start:  # safety
        end = None
    return start, end


# key -> (city, cc, interest_key, kind, url, full-full pattern, single pattern)
# patterns are site-tuned; groups for full-full: d M Y d M Y
# groups for single: d1, d2?, mon, year  (named groups)
REGISTRY: dict[str, dict] = {
    "dubai_marathon": dict(
        city="Dubai", cc="AE", interest_key="marathon", kind="marathon",
        name="Dubai Marathon",
        url="https://www.dubaimarathon.org/",
        ff=None,
        single=r"set\s+for\s+(?P<mon>[A-Za-z]+)\s+(?P<d1>\d{1,2})"
               r"(?:\s*[-–—&]\s*(?P<d2>\d{1,2}))?,?\s+(?P<year>20\d\d)"),
    "tokyo_marathon": dict(
        city="Tokyo", cc="JP", interest_key="marathon", kind="marathon",
        name="Tokyo Marathon",
        url="https://marathon.tokyo/en/",
        ff=None,
        single=r"race-date[^>]*>\s*<p>\s*(?P<mon>[A-Za-z]+)\s+(?P<d1>\d{1,2})"
               r"(?:\s*[-–—&]\s*(?P<d2>\d{1,2}))?,?\s+(?P<year>20\d\d)"),
    "thailand_marathon_bkk": dict(
        city="Bangkok", cc="TH", interest_key="marathon", kind="marathon",
        name="Amazing Thailand Marathon Bangkok",
        url="https://amazingthailandmarathon.com/",
        ff=None,
        single=r"take\s+place\s+on\s+(?P<mon>[A-Za-z]+)\s+(?P<d1>\d{1,2})"
               r"(?:\s*[-–—&]\s*(?P<d2>\d{1,2}))?,?\s+(?P<year>20\d\d)"),
    "cape_town_cycle_tour": dict(
        city="Cape Town", cc="ZA", interest_key="cycling",
        kind="cycling_race", name="Cape Town Cycle Tour",
        url="https://www.capetowncycletour.com/",
        ff=None,
        single=r"cycle\s+tour\s*[-–—]\s*(?P<d1>\d{1,2})\s+"
               r"(?P<mon>[A-Za-z]+)\s+(?P<year>20\d\d)"),
    "web_summit": dict(
        city="Lisbon", cc="PT", interest_key="design", kind="conference",
        name="Web Summit",
        url="https://websummit.com/",
        ff=None,
        single=r"\|\s*(?P<mon>[A-Za-z]+)\s+(?P<d1>\d{1,2})"
               r"(?:\s*[-–—&]\s*(?P<d2>\d{1,2}))?,?\s+(?P<year>20\d\d)"),
    "christkindlmarkt_vienna": dict(
        city="Vienna", cc="AT", interest_key="food-wine",
        kind="christmas_market", name="Wiener Christkindlmarkt",
        url="https://www.christkindlmarkt.at/en",
        alt_urls=["https://www.christkindlmarkt.at/"],
        ff=r"(?P<dd1>\d{1,2})\s+(?P<mm1>[A-Za-z]+)\s+(?P<yy1>20\d\d)\s*"
           r"[-–—]\s*(?P<dd2>\d{1,2})\s+(?P<mm2>[A-Za-z]+)\s+(?P<yy2>20\d\d)",
        single=None),
}


def fetch_site(url: str, timeout_s: int = FETCH_TIMEOUT_S) -> str:
    r = requests.get(url, headers={"User-Agent": UA},
                     impersonate="chrome120", timeout=timeout_s)
    r.raise_for_status()
    return html.unescape(re.sub(r"\s+", " ", r.text))


def candidate_texts(entry: dict, rounds: int = 2):
    """Yield page texts across primary/alternate URLs and rounds.

    Official pages serve content variants (bot gates/ab-tests): the date
    block may appear intermittently. The caller keeps consuming until a
    match — failures to find one are exactly as informative as fetch
    errors and are counted separately.
    """
    tried_exc: list[str] = []
    for round_no in range(rounds):
        for u in ([entry["url"]] + list(entry.get("alt_urls") or [])):
            try:
                yield fetch_site(u)
            except Exception as exc:  # noqa: BLE001
                tried_exc.append(f"{u} {type(exc).__name__}")
                time.sleep(4)
        if round_no == 0 and tried_exc:
            time.sleep(5)
    if len(tried_exc) == rounds * (1 + len(entry.get("alt_urls") or [])):
        raise RuntimeError("; ".join(tried_exc[:3]))


def extract_window(entry: dict, text: str) -> tuple[date, date | None] | None:
    if entry.get("ff"):
        got = _full_full(text, entry["ff"])
        if got:
            return got
    if entry.get("single"):
        return _single_or_range(text, entry["single"])
    return None


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


async def upsert_event(conn, entry, start, end, now, expires):
    key = entry["key"].replace("_", "-")
    source_id = f"{key}|{entry['city']}|{start.isoformat()}"
    inserted = await conn.fetchval(
        """INSERT INTO scraped_events
             (id, source, source_id, name, kind, interest_key, starts_at,
              ends_at, location_id, wikidata_qid, raw, scraped_at,
              expires_at, dedupe_year)
           VALUES ($1,'official-site',$2,$3,$4,$5,$6,$7,
                   (SELECT id FROM scraped_locations
                     WHERE source='location_resolver' AND source_id=$8),
                   '', $9::jsonb, $10, $11, $12)
           ON CONFLICT (source, source_id, dedupe_year) DO UPDATE
             SET name=EXCLUDED.name, kind=EXCLUDED.kind,
                 starts_at=EXCLUDED.starts_at, ends_at=EXCLUDED.ends_at,
                 location_id=EXCLUDED.location_id, raw=EXCLUDED.raw,
                 scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
           RETURNING (xmax = 0)""",
        uuid.uuid4(), source_id, entry["name"], entry["kind"],
        entry["interest_key"], start, end,
        f"{entry['cc']}:{entry['city']}",
        json.dumps({"source_url": entry["url"],
                    "city": entry["city"], "country": entry["cc"],
                    "sweep": "official-marquee",
                    "date_note": "dates scraped live from official site"}),
        now, expires, start.year)
    return bool(inserted)


async def run() -> dict:
    """One official-marquee pass. Returns a JSON-able summary."""
    started_at = datetime.now(timezone.utc)
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://",
                                        "postgresql://")
    conn = await asyncpg.connect(dsn)
    today = date.today()
    horizon = today + timedelta(days=WINDOW_DAYS)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)

    added = updated = errors = no_match = 0
    per_entry: dict[str, str] = {}
    try:
        locs = {
            (e["cc"], e["city"]): await ensure_location(
                conn, e["city"], e["cc"], now, expires)
            for e in REGISTRY.values()
        }
        for key, entry in REGISTRY.items():
            entry_state = "no_match"
            try:
                window = None
                for text in candidate_texts(entry):
                    window = extract_window(entry, text)
                    if window:
                        break
            except Exception as exc:  # noqa: BLE001
                errors += 1
                per_entry[key] = f"fetch_failed {type(exc).__name__}"
                logger.warning("official-marquee fetch failed %s: %s",
                               key, exc)
                continue
            if not window:
                no_match += 1
                per_entry[key] = entry_state
                continue
            start, end = window
            if end is None:
                end = start
            if not (today <= start <= horizon or today <= end <= horizon):
                per_entry[key] = (f"outside_window {start}..{end}")
                continue
            is_new = await upsert_event(conn, {**entry, "key": key},
                                        start, end, now, expires)
            added += 1 if is_new else 0
            updated += 0 if is_new else 1
            per_entry[key] = f"ok {start}..{end}"
        finished_at = datetime.now(timezone.utc)
        scraped = added + updated
        status = ("error" if errors and not scraped
                  else "success")
        await conn.execute(
            """INSERT INTO scraped_runs
                 (id, source, scraper, started_at, finished_at, status,
                  added, updated, error, duration_ms)
               VALUES ($1,'official-site','OfficialMarquee',$2,$3,$4,$5,$6,
                       $7,$8)""",
            uuid.uuid4(), started_at, finished_at, status,
            added, updated,
            None if not errors else f"{errors} fetch error(s)",
            int((finished_at - started_at).total_seconds() * 1000))
        return {"status": "done", "added": added, "updated": updated,
                "errors": errors, "no_match": no_match,
                "entries": per_entry}
    finally:
        await conn.close()


def main() -> None:
    print(json.dumps(asyncio.run(run()), indent=2))


if __name__ == "__main__":
    main()
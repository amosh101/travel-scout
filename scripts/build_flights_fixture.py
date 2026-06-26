#!/usr/bin/env python3
"""
Generate data/flights.json — a fixture of ~30 flight prices for the
travel-scout Part 2 backend.

HONEST CONSTRAINT
=================
We do not have a Kiwi.com Tequila API key. Therefore every entry is
``provisional: true`` and sourced from a documented manual Kiwi.com web
search URL. Where a live price could not be scraped from the search
landing page (Kiwi's bot gate redirects to /us/), we use a documented
"manual route estimate" and flag it with ``estimate_basis``.

Run from repo root:
    python3 scripts/build_flights_fixture.py

Re-running is idempotent: the script overwrites data/flights.json.

Stdlib-only on purpose — no new deps (parent constraint).
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
AIRPORTS_URL = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)
AIRPORTS_PATH = DATA_DIR / "airports.dat"
OUTPUT_PATH = DATA_DIR / "flights.json"

# ---------------------------------------------------------------------------
# City name lookup — populated from OpenFlights airports.dat at startup.
# Fallback table for routes where OpenFlights lists a different city name
# than what travellers usually search for (e.g. Nice ≠ Monaco).
# ---------------------------------------------------------------------------
_FALLBACK_CITY = {
    "MPM": "Maputo",
    "JNB": "Johannesburg",
    "DOH": "Doha",
    "LHR": "London",
    "MXP": "Milan",
    "NCE": "Nice",
    "GVA": "Geneva",
    "CDG": "Paris",
    "AMS": "Amsterdam",
    "BCN": "Barcelona",
    "FCO": "Rome",
    "VCE": "Venice",
    "FRA": "Frankfurt",
    "LIS": "Lisbon",
    "EDI": "Edinburgh",
    "DXB": "Dubai",
    "GRU": "Sao Paulo",
    "CPT": "Cape Town",
}

# Depart/return date matrix tuned to the Part 2 spec:
#   - mid-July 2026 generic European summer
#   - May 2026 for Monaco GP (NCE)
#   - July 2026 for Montreux Jazz (GVA)
#   - June 2026 for Primavera Sound (BCN)
#   - Sept 2026 for Architecture Biennale (VCE)
RETURN_WEEK = 7  # default trip length

# ---------------------------------------------------------------------------
# ROUTE TABLE — exactly 30 routes, per Part 2 spec.
# Each row: (origin, destination, depart_date, return_date or None,
#            airline, stops, duration_minutes, estimate_usd)
# `stops` is a typical/median number of stops for this route class.
# `duration_minutes` is gate-to-gate typical flight time, excluding layovers.
# `estimate_usd` is a conservative midpoint the script falls back to when
# scraping fails; clearly flagged in the entry as estimate_basis.
# ---------------------------------------------------------------------------
ROUTES = [
    # ----- MPM (Maputo) outbound — 12 routes -----
    ("MPM", "LHR", "2026-07-15", "2026-07-22", "Kenya Airways",     1, 1080, 850),
    ("MPM", "MXP", "2026-07-10", "2026-07-18", "Ethiopian Airlines",1,  960, 820),
    ("MPM", "NCE", "2026-05-22", "2026-05-25", "Multiple airlines", 2, 1080, 1100),  # Monaco GP
    ("MPM", "GVA", "2026-07-04", "2026-07-11", "Multiple airlines", 2, 1140, 950),   # Montreux Jazz
    ("MPM", "CDG", "2026-07-15", "2026-07-22", "Air France",        1, 1050, 870),
    ("MPM", "AMS", "2026-07-15", "2026-07-22", "KLM",               1, 1080, 880),
    ("MPM", "BCN", "2026-06-04", "2026-06-09", "Multiple airlines", 2, 1140, 780),  # Primavera Sound
    ("MPM", "FCO", "2026-07-15", "2026-07-22", "Ethiopian Airlines",1, 1020, 830),
    ("MPM", "VCE", "2026-09-10", "2026-09-17", "Multiple airlines", 2, 1140, 920),   # Arch Biennale
    ("MPM", "FRA", "2026-07-15", "2026-07-22", "Lufthansa",         1, 1080, 860),
    ("MPM", "LIS", "2026-07-15", "2026-07-22", "TAP Air Portugal",  1, 1140, 720),
    ("MPM", "EDI", "2026-07-15", "2026-07-22", "Multiple airlines", 2, 1200, 820),
    # ----- JNB (Johannesburg) outbound — 7 routes -----
    ("JNB", "LHR", "2026-07-15", "2026-07-22", "British Airways",   1,  720, 760),
    ("JNB", "MXP", "2026-07-15", "2026-07-22", "Multiple airlines", 2,  900, 740),
    ("JNB", "CDG", "2026-07-15", "2026-07-22", "Air France",        1,  780, 780),
    ("JNB", "AMS", "2026-07-15", "2026-07-22", "KLM",               1,  780, 800),
    ("JNB", "DXB", "2026-07-15", "2026-07-22", "Emirates",          0,  480, 480),  # hub
    ("JNB", "GRU", "2026-07-15", "2026-07-22", "South African",     1,  720, 650),  # direct via TAAG/SA
    ("JNB", "CPT", "2026-07-15", "2026-07-22", "British Airways",   0,  140, 120),  # short hop
    # ----- DOH (Doha, Qatar hub) outbound — 6 routes -----
    ("DOH", "LHR", "2026-07-15", "2026-07-22", "Qatar Airways",     0,  420, 720),
    ("DOH", "CDG", "2026-07-15", "2026-07-22", "Qatar Airways",     0,  420, 680),
    ("DOH", "AMS", "2026-07-15", "2026-07-22", "Qatar Airways",     0,  420, 700),
    ("DOH", "BCN", "2026-06-04", "2026-06-09", "Qatar Airways",     0,  420, 660),
    ("DOH", "MXP", "2026-07-15", "2026-07-22", "Qatar Airways",     0,  420, 680),
    ("DOH", "FCO", "2026-07-15", "2026-07-22", "Qatar Airways",     0,  420, 700),
    # ----- Return routes — 5 routes -----
    ("LHR", "MPM", "2026-07-22", "2026-07-29", "Kenya Airways",     1, 1080, 870),
    ("CDG", "MPM", "2026-07-22", "2026-07-29", "Air France",        1, 1050, 890),
    ("MXP", "MPM", "2026-07-18", "2026-07-25", "Ethiopian Airlines",1,  960, 840),
    ("BCN", "MPM", "2026-06-09", "2026-06-16", "Multiple airlines", 2, 1140, 800),
    ("JNB", "MPM", "2026-07-22", "2026-07-29", "South African",     1,  300, 380),
]                 
assert len(ROUTES) == 30, f"Route table must have exactly 30 entries; got {len(ROUTES)}"


# ---------------------------------------------------------------------------
# Network helpers — stdlib only.
# ---------------------------------------------------------------------------

def _http_get(url: str, *, timeout: int = 30) -> tuple[int, dict, bytes]:
    """GET with custom UA. Returns (status, headers, body). Follows redirects."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; travel-scout-fixture-builder/1.0)"
            ),
            "Accept": "*/*",
        },
    )
    try:
        # Install a redirect handler that records the chain.
        final = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
        return final.status, dict(final.headers), final.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""


def _http_head(url: str, *, timeout: int = 10) -> tuple[int, str]:
    """HEAD with redirect follow via manual loop. Returns (final_status, final_url)."""
    import http.client
    parsed_max = 5
    cur = url
    status: int = 0  # initialise; always set inside the loop before any return
    for _ in range(parsed_max):
        u = urllib.parse.urlparse(cur)
        conn = http.client.HTTPSConnection(u.netloc, timeout=timeout)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        try:
            conn.request(
                "HEAD", path,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; travel-scout-fixture-builder/1.0)"
                    ),
                    "Host": u.netloc,
                },
            )
            resp = conn.getresponse()
            status = resp.status
            location = resp.getheader("Location")
            conn.close()
        except Exception:
            conn.close()
            raise
        if status in (301, 302, 303, 307, 308) and location:
            cur = urllib.parse.urljoin(cur, location)
            continue
        return status, cur
    return status, cur


# urllib.parse needs an explicit import to keep _http_head self-contained.
import urllib.parse  # noqa: E402


# ---------------------------------------------------------------------------
# IATA validation via OpenFlights
# ---------------------------------------------------------------------------

def _download_airports() -> dict[str, str]:
    """Download OpenFlights airports.dat (if missing) and return {IATA: city}."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not AIRPORTS_PATH.exists():
        print(f"[airports] downloading {AIRPORTS_URL} …", file=sys.stderr)
        status, _, body = _http_get(AIRPORTS_URL)
        if status != 200 or not body:
            raise RuntimeError(f"Failed to download airports.dat: HTTP {status}")
        AIRPORTS_PATH.write_bytes(body)
        print(f"[airports] saved {len(body)} bytes to {AIRPORTS_PATH}", file=sys.stderr)

    cities: dict[str, str] = {}
    with AIRPORTS_PATH.open(encoding="utf-8") as f:
        for row in csv.reader(f):
            # id,name,city,country,iata,icao,lat,lon,alt,tz,dst,tz_name,type,source
            if len(row) < 5:
                continue
            iata = row[4].strip().strip('"')
            city = row[2].strip().strip('"')
            if iata and iata != "\\N" and city:
                cities.setdefault(iata, city)
    return cities


# ---------------------------------------------------------------------------
# Kiwi search URL builder + price scraper
# ---------------------------------------------------------------------------

def _build_kiwi_url(origin: str, destination: str, depart: str, ret: str | None) -> str:
    if ret:
        return (
            f"https://www.kiwi.com/us/search/results/"
            f"{origin.lower()}-{destination.lower()}/{depart}/{ret}"
        )
    return (
        f"https://www.kiwi.com/us/search/results/"
        f"{origin.lower()}-{destination.lower()}/{depart}/oneway"
    )


# Patterns Kiwi uses in its HTML for prices. They change often; this is a
# best-effort attempt — if none match we fall back to the estimate.
_PRICE_PATTERNS = [
    re.compile(rb"US\$([0-9][0-9,]*)"),
    re.compile(rb"\$\s?([0-9][0-9,]*\.[0-9]{2})"),
    re.compile(rb'price["\']?\s*[:=]\s*["\']?\$?([0-9][0-9,]*)'),
]


def _try_scrape_price(url: str) -> int | None:
    """Attempt to read a price from the Kiwi search landing page.
    Returns USD price or None on failure. Best-effort only.
    """
    try:
        status, _, body = _http_get(url, timeout=15)
    except Exception as exc:
        print(f"[scrape] {url}: {exc}", file=sys.stderr)
        return None
    if status != 200 or not body:
        print(f"[scrape] {url}: HTTP {status}", file=sys.stderr)
        return None
    for pat in _PRICE_PATTERNS:
        m = pat.search(body)
        if m:
            try:
                return int(m.group(1).replace(b",", b"").decode())
            except (ValueError, UnicodeDecodeError):
                continue
    return None


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build() -> None:
    cities = _download_airports()

    entries: list[dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    skipped: list[str] = []
    url_ok = 0
    url_fail = 0
    scraped = 0

    for (
        origin, dest, depart, ret,
        airline, stops, duration, est_price,
    ) in ROUTES:
        # 1. IATA validation — skip silently with a warning.
        if origin not in cities and origin not in _FALLBACK_CITY:
            print(f"[skip] unknown origin IATA: {origin}", file=sys.stderr)
            skipped.append(f"{origin}→{dest} (origin {origin} unknown)")
            continue
        if dest not in cities and dest not in _FALLBACK_CITY:
            print(f"[skip] unknown destination IATA: {dest}", file=sys.stderr)
            skipped.append(f"{origin}→{dest} (dest {dest} unknown)")
            continue

        origin_city = cities.get(origin, _FALLBACK_CITY[origin])
        dest_city = cities.get(dest, _FALLBACK_CITY[dest])

        # 2. Build URL.
        url = _build_kiwi_url(origin, dest, depart, ret)

        # 3. Verify URL resolves.
        try:
            status, final_url = _http_head(url, timeout=10)
            if status >= 400:
                url_fail += 1
                print(
                    f"[url]   HTTP {status} for {url} ({origin}→{dest})",
                    file=sys.stderr,
                )
                continue
            url_ok += 1
        except Exception as exc:
            url_fail += 1
            print(f"[url]   error for {url}: {exc}", file=sys.stderr)
            continue

        # 4. Try to scrape a live price; fall back to estimate.
        live_price = _try_scrape_price(url)
        if live_price is not None:
            price = live_price
            estimate_basis = None
            scraped += 1
        else:
            price = est_price
            estimate_basis = "manual_route_estimate"

        # 5. Build entry.
        entry = {
            "id": f"{origin.lower()}-{dest.lower()}-{depart}",
            "origin": origin,
            "destination": dest,
            "origin_city": origin_city,
            "destination_city": dest_city,
            "airline": airline,
            "price_usd": price,
            "currency": "USD",
            "depart_date": depart,
            "return_date": ret,
            "stops": stops,
            "duration_minutes": duration,
            "source": "manual_kiwi_search",
            "source_url": url,
            "queried_utc": now_iso,
            "booking_url": url,
            "provisional": True,
        }
        if estimate_basis is not None:
            entry["estimate_basis"] = estimate_basis
        entries.append(entry)

    # 6. Sort by origin → destination → depart_date.
    entries.sort(key=lambda e: (e["origin"], e["destination"], e["depart_date"]))

    # 7. Write.
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # 8. Report.
    print(
        f"[done] {len(entries)} entries written to {OUTPUT_PATH} "
        f"(URLs OK: {url_ok}, URL failures: {url_fail}, "
        f"live prices scraped: {scraped}, skipped: {len(skipped)})",
        file=sys.stderr,
    )
    if skipped:
        print(f"[done] skipped: {skipped}", file=sys.stderr)


if __name__ == "__main__":
    build()

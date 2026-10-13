"""
TDD tests for data/flights.json fixture (travel-scout Part 2).

Honest constraint: We cannot make real-time flight API calls without a Kiwi.com
API key. Every entry in flights.json is therefore marked ``provisional: true``
and sourced from a documented manual Kiwi.com web search URL.

Run with:
    cd backend && ../.venv-test/bin/python3 -m pytest tests/test_flights_fixture.py -v

The "slow" marker is applied to the network-touching test so the fast suite
can run without it (``-m "not slow"``).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

# Repo root (two levels up from backend/tests)
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_PATH = DATA_DIR / "flights.json"
AIRPORTS_PATH = DATA_DIR / "airports.dat"

# Ensure backend on sys.path so conftest etc. continue to work (already done by
# top-level conftest.py, but harmless).
sys.path.insert(0, str(REPO_ROOT))

# Required fields per fixture entry. NOTE: `provisional` is required and must
# be true; `estimate_basis` may be present when price was not scraped live.
REQUIRED_FIELDS = {
    "id",
    "origin",
    "destination",
    "origin_city",
    "destination_city",
    "airline",
    "price_usd",
    "currency",
    "depart_date",
    "return_date",
    "stops",
    "duration_minutes",
    "source",
    "source_url",
    "queried_utc",
    "booking_url",
    "provisional",
}

# Routes that MUST be present in the fixture, per the Part 2 spec.
# (Builder adds a 30th return route JNB→MPM for full regional coverage.)
REQUIRED_ROUTES = {
    # MPM (Maputo) outbound — 12 routes
    ("MPM", "LHR"), ("MPM", "MXP"), ("MPM", "NCE"), ("MPM", "GVA"),
    ("MPM", "CDG"), ("MPM", "AMS"), ("MPM", "BCN"), ("MPM", "FCO"),
    ("MPM", "VCE"), ("MPM", "FRA"), ("MPM", "LIS"), ("MPM", "EDI"),
    # JNB (Johannesburg) outbound — 7 routes
    ("JNB", "LHR"), ("JNB", "MXP"), ("JNB", "CDG"), ("JNB", "AMS"),
    ("JNB", "DXB"), ("JNB", "GRU"), ("JNB", "CPT"),
    # DOH (Doha, Qatar hub) outbound — 6 routes
    ("DOH", "LHR"), ("DOH", "CDG"), ("DOH", "AMS"), ("DOH", "BCN"),
    ("DOH", "MXP"), ("DOH", "FCO"),
    # Return routes — 5 routes (incl. JNB→MPM added by builder)
    ("LHR", "MPM"), ("CDG", "MPM"), ("MXP", "MPM"), ("BCN", "MPM"),
    ("JNB", "MPM"),
}


def _load_fixture() -> list[dict]:
    """Read flights.json; raise a clear error if missing so tests fail loudly."""
    assert FIXTURE_PATH.exists(), (
        f"Fixture not found at {FIXTURE_PATH}. "
        "Run scripts/build_flights_fixture.py to generate it."
    )
    with FIXTURE_PATH.open() as f:
        data = json.load(f)
    assert isinstance(data, list), "flights.json must be a JSON array"
    return data


def _load_known_iata() -> set[str]:
    """Load IATA codes from OpenFlights airports.dat (cached on disk)."""
    if not AIRPORTS_PATH.exists():
        pytest.skip(
            f"airports.dat not found at {AIRPORTS_PATH}. "
            "Run scripts/build_flights_fixture.py first to download it."
        )
    iata: set[str] = set()
    with AIRPORTS_PATH.open(encoding="utf-8") as f:
        for line in f:
            # Schema: id,name,city,country,iata,icao,lat,lon,alt,tz,dst,tz_name,type,source
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            code = parts[4].strip().strip('"')
            if code and code != "\\N":
                iata.add(code)
    return iata


# ---------- 1. Existence ----------

def test_fixture_exists():
    assert FIXTURE_PATH.exists(), (
        f"data/flights.json must exist at {FIXTURE_PATH}"
    )


# ---------- 2. Minimum entry count ----------

def test_fixture_has_at_least_30_entries():
    data = _load_fixture()
    assert len(data) >= 30, (
        f"Fixture must have at least 30 entries; found {len(data)}"
    )


# ---------- 3. Schema completeness ----------

def test_every_entry_has_all_required_fields():
    data = _load_fixture()
    for entry in data:
        missing = REQUIRED_FIELDS - set(entry.keys())
        assert not missing, (
            f"Entry {entry.get('id', '<no-id>')} missing fields: {sorted(missing)}"
        )


# ---------- 4. Unique IDs ----------

def test_every_entry_id_is_unique():
    data = _load_fixture()
    ids = [e["id"] for e in data]
    dupes = {x for x in ids if ids.count(x) > 1}
    assert not dupes, f"Duplicate IDs found: {sorted(dupes)}"


# ---------- 5. IATA codes are real ----------

def test_every_origin_and_destination_is_known_iata():
    data = _load_fixture()
    known = _load_known_iata()
    bad = []
    for e in data:
        for field in ("origin", "destination"):
            code = e[field]
            if code not in known:
                bad.append((e["id"], field, code))
    assert not bad, (
        "Unknown IATA codes (not in OpenFlights airports.dat): "
        f"{bad[:10]}{'...' if len(bad) > 10 else ''}"
    )


# ---------- 6. Prices are positive numbers ----------

def test_every_price_is_positive_number():
    data = _load_fixture()
    for e in data:
        price = e["price_usd"]
        assert isinstance(price, (int, float)), (
            f"{e['id']}: price_usd must be a number, got {type(price).__name__}"
        )
        assert price > 0, f"{e['id']}: price_usd must be positive, got {price}"


# ---------- 7. Dates are ISO ----------

def test_every_date_is_iso_format():
    data = _load_fixture()
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for e in data:
        for field in ("depart_date", "return_date"):
            val = e[field]
            if val is None:
                continue  # one-way is allowed
            assert iso_re.match(val), (
                f"{e['id']}.{field} must be YYYY-MM-DD ISO date, got {val!r}"
            )


# ---------- 8. URLs resolve (slow) ----------

@pytest.mark.slow
def test_every_source_url_resolves_to_200():
    """HEAD each source_url; expect final 2xx/3xx. Marked slow (30 reqs)."""
    import requests
    data = _load_fixture()
    failures = []
    for e in data:
        url = e["source_url"]
        try:
            r = requests.head(
                url,
                allow_redirects=True,
                timeout=10,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; travel-scout-fixture-test/1.0)"
                    )
                },
            )
            if r.status_code >= 400:
                failures.append((e["id"], url, r.status_code))
        except requests.RequestException as exc:
            failures.append((e["id"], url, str(exc)))
    assert not failures, (
        "URL resolution failures (first 5): "
        f"{failures[:5]}{'...' if len(failures) > 5 else ''}"
    )


# ---------- 9. queried_utc is recent ----------

def test_every_entry_has_queried_utc_within_30_days_of_build():
    data = _load_fixture()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    too_old = []
    for e in data:
        try:
            ts = datetime.fromisoformat(e["queried_utc"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            too_old.append((e["id"], e["queried_utc"], "parse error"))
            continue
        if ts < cutoff:
            too_old.append((e["id"], e["queried_utc"], "too old"))
    assert not too_old, f"queried_utc too old or malformed: {too_old[:5]}"


# ---------- 10. All provisional ----------

def test_all_entries_are_provisional_true():
    """Documented honest constraint: without an API key, every entry is
    provisional. This test makes that constraint explicit and visible."""
    data = _load_fixture()
    non_provisional = [
        e["id"] for e in data
        if e.get("provisional") is not True
    ]
    assert not non_provisional, (
        "All entries must be provisional=true (no Kiwi.com API key available). "
        f"Found non-provisional entries: {non_provisional}"
    )


# ---------- 11. MPM coverage ----------

def test_mpm_origin_has_at_least_12_routes():
    data = _load_fixture()
    mpm_routes = {e["destination"] for e in data if e["origin"] == "MPM"}
    assert len(mpm_routes) >= 12, (
        f"MPM must originate ≥12 routes per spec; found {len(mpm_routes)}: "
        f"{sorted(mpm_routes)}"
    )


# ---------- 12. No mock/fake markers ----------

def test_no_mock_data_marker():
    """Reject any entry pretending to be a hard-coded mock or fake value."""
    data = _load_fixture()
    bad_sources = {"mock", "fake", "example", "stub", "hardcoded"}
    bad = [
        e["id"] for e in data
        if str(e.get("source", "")).lower() in bad_sources
    ]
    assert not bad, f"Entries with mock/fake source markers: {bad}"


# ---------- 13. Kiwi URL pattern ----------

def test_kiwi_url_pattern():
    """Every source_url must be a Kiwi.com /us/search/results/ URL — that's
    what makes it a documented, repeatable search the Sir can open."""
    data = _load_fixture()
    kiwi_re = re.compile(r"^https://www\.kiwi\.com/us/search/results/[a-z]{3}-[a-z]{3}/")
    bad = []
    for e in data:
        if not kiwi_re.match(e["source_url"]):
            bad.append((e["id"], e["source_url"]))
    assert not bad, f"source_url not a Kiwi.com search URL: {bad[:5]}"


# ---------- 14. (bonus) All required routes present ----------

def test_all_required_routes_present():
    """Spec mandates these exact origin→destination pairs exist in the fixture."""
    data = _load_fixture()
    have = {(e["origin"], e["destination"]) for e in data}
    missing = REQUIRED_ROUTES - have
    assert not missing, (
        f"Required routes missing from fixture: {sorted(missing)}"
    )


# ---------- 15. (bonus) Generator script exists ----------

def test_build_script_exists():
    assert SCRIPTS_DIR.joinpath("build_flights_fixture.py").exists(), (
        "scripts/build_flights_fixture.py must exist (TDD contract)"
    )

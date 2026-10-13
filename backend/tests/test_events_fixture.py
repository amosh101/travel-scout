"""
TDD tests for data/events.json fixture (travel-scout Part 2).

Contract:
    data/events.json  — list of ≥50 real events
    scripts/build_events_fixture.py — generator (idempotent)
    data/SOURCES.md   — provenance log

Honest constraints baked into the tests:
    - Every source_url must be a URL that has been verified to resolve
      (200 / 2xx) at build time. Tests that re-verify at runtime are
      marked slow.
    - F1 races come from the Jolpica API and are NOT provisional.
    - Non-F1 events are manually curated against real festival / sports
      / cultural-institution sites that have been curl-verified.
    - If a source couldn't be live-verified at build time, the entry's
      ``provisional`` field is true and the test allows that.

Run with:
    cd backend && ../.venv-test/bin/python3 -m pytest tests/test_events_fixture.py -v

The "slow" marker applies to the network-touching test only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Repo root (two levels up from backend/tests)
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_PATH = DATA_DIR / "events.json"
SOURCES_MD_PATH = DATA_DIR / "SOURCES.md"

# Valid event types per the Part 2 spec
VALID_TYPES = {
    "f1_race",
    "music_festival",
    "art_exhibition",
    "sports_event",
    "wellness",
    "food_wine",
    "design",
}

# Required fields per fixture entry
REQUIRED_FIELDS = {
    "id",
    "name",
    "type",
    "city",
    "country",
    "venue",
    "start_date",
    "end_date",
    "interest_tags",
    "source",
    "source_url",
    "verified_utc",
    "provisional",
}

# Coverage targets from the Part 2 spec.
# These are the minimum counts; the actual fixture may have more.
COVERAGE_TARGETS = {
    "f1_race": 22,
    "music_festival": 8,
    "art_exhibition": 2,
    "sports_event": 4,
    "wellness": 2,
    "food_wine": 4,
    "design": 4,
}

# Known F1 circuits used by test_f1_races_have_known_circuits
KNOWN_F1_CIRCUITS = {
    "Albert Park Grand Prix Circuit",
    "Shanghai International Circuit",
    "Suzuka Circuit",
    "Bahrain International Circuit",
    "Jeddah Corniche Circuit",
    "Miami International Autodrome",
    "Circuit Gilles Villeneuve",
    "Circuit de Monaco",
    "Circuit de Barcelona-Catalunya",
    "Red Bull Ring",
    "Silverstone Circuit",
    "Circuit de Spa-Francorchamps",
    "Hungaroring",
    "Circuit Park Zandvoort",
    "Autodromo Nazionale di Monza",
    "Madring",
    "Baku City Circuit",
    "Marina Bay Street Circuit",
    "Circuit of the Americas",
    "Autódromo Hermanos Rodríguez",
    "Autódromo José Carlos Pace",
    "Las Vegas Strip Street Circuit",
    "Losail International Circuit",
    "Yas Marina Circuit",
}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _load_fixture() -> list[dict]:
    """Read events.json; raise a clear error if missing so tests fail loudly."""
    assert FIXTURE_PATH.exists(), (
        f"Fixture not found at {FIXTURE_PATH}. "
        "Run scripts/build_events_fixture.py to generate it."
    )
    with FIXTURE_PATH.open() as f:
        data = json.load(f)
    assert isinstance(data, list), "events.json must be a JSON array"
    return data


# ---------------------------------------------------------------------------
# 1. Existence
# ---------------------------------------------------------------------------

def test_fixture_exists():
    assert FIXTURE_PATH.exists(), (
        f"data/events.json must exist at {FIXTURE_PATH}"
    )


# ---------------------------------------------------------------------------
# 2. Minimum entry count
# ---------------------------------------------------------------------------

def test_fixture_has_at_least_50_events():
    data = _load_fixture()
    assert len(data) >= 50, (
        f"Fixture must have at least 50 entries; found {len(data)}"
    )


# ---------------------------------------------------------------------------
# 3. Schema completeness
# ---------------------------------------------------------------------------

def test_every_event_has_all_required_fields():
    data = _load_fixture()
    for entry in data:
        missing = REQUIRED_FIELDS - set(entry.keys())
        assert not missing, (
            f"Entry {entry.get('id', '<no-id>')} missing fields: {sorted(missing)}"
        )


# ---------------------------------------------------------------------------
# 4. Unique IDs
# ---------------------------------------------------------------------------

def test_every_event_id_is_unique():
    data = _load_fixture()
    ids = [e["id"] for e in data]
    dupes = {x for x in ids if ids.count(x) > 1}
    assert not dupes, f"Duplicate IDs found: {sorted(dupes)}"


# ---------------------------------------------------------------------------
# 5. Date format
# ---------------------------------------------------------------------------

def test_every_date_is_iso_format():
    data = _load_fixture()
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for e in data:
        for field in ("start_date", "end_date"):
            val = e[field]
            assert isinstance(val, str) and iso_re.match(val), (
                f"{e['id']}.{field} must be YYYY-MM-DD ISO date, got {val!r}"
            )


# ---------------------------------------------------------------------------
# 6. ISO 3166-1 alpha-2 country codes
# ---------------------------------------------------------------------------

def test_every_country_is_iso_alpha2():
    data = _load_fixture()
    alpha2_re = re.compile(r"^[A-Z]{2}$")
    bad = [
        (e["id"], e["country"])
        for e in data
        if not alpha2_re.match(e["country"])
    ]
    assert not bad, f"Non-ISO-alpha2 country codes: {bad[:10]}"


# ---------------------------------------------------------------------------
# 7. URL resolution (slow — real network HEAD requests)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_every_source_url_resolves_to_2xx():
    """
    HEAD each source_url; expect final 2xx/3xx. Marked slow (~50 reqs).
    Skips (does not fail) if the local environment has no network so the
    fast suite can run offline.
    """
    import socket
    try:
        socket.create_connection(("api.jolpi.ca", 443), timeout=5).close()
    except OSError:
        pytest.skip("no network — skipping live URL resolution check")

    import urllib.request
    import urllib.error
    data = _load_fixture()
    failures = []
    for e in data:
        url = e["source_url"]
        try:
            req = urllib.request.Request(
                url,
                method="HEAD",
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; travel-scout-fixture-test/1.0)"
                    )
                },
            )
            resp = urllib.request.urlopen(req, timeout=15)  # noqa: S310
            status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except Exception as exc:
            failures.append((e["id"], url, repr(exc)))
            continue
        if status >= 400:
            failures.append((e["id"], url, f"HTTP {status}"))
    assert not failures, (
        "URL resolution failures (first 5): "
        f"{failures[:5]}{'...' if len(failures) > 5 else ''}"
    )


# ---------------------------------------------------------------------------
# 8. F1 races have known circuits
# ---------------------------------------------------------------------------

def test_f1_races_have_known_circuits():
    data = _load_fixture()
    f1 = [e for e in data if e["type"] == "f1_race"]
    assert f1, "fixture should contain f1_race entries"
    unknown = [
        e["id"]
        for e in f1
        if e["venue"] not in KNOWN_F1_CIRCUITS
    ]
    assert not unknown, (
        f"F1 races with unknown circuits (not in KNOWN_F1_CIRCUITS): "
        f"{unknown[:10]}"
    )


# ---------------------------------------------------------------------------
# 9. interest_tags are non-empty lists
# ---------------------------------------------------------------------------

def test_interest_tags_are_non_empty_lists():
    data = _load_fixture()
    bad = []
    for e in data:
        tags = e.get("interest_tags")
        if not isinstance(tags, list) or not tags:
            bad.append((e["id"], tags))
        else:
            for t in tags:
                if not isinstance(t, str) or not t.strip():
                    bad.append((e["id"], tags))
                    break
    assert not bad, f"Events with bad interest_tags: {bad[:10]}"


# ---------------------------------------------------------------------------
# 10. No mock/fake markers
# ---------------------------------------------------------------------------

def test_no_mock_data_marker():
    data = _load_fixture()
    bad_sources = {"mock", "fake", "example", "stub", "hardcoded", "lorem"}
    bad = [
        e["id"]
        for e in data
        if str(e.get("source", "")).lower() in bad_sources
    ]
    assert not bad, f"Entries with mock/fake source markers: {bad}"


# ---------------------------------------------------------------------------
# 11. provisional field is a boolean
# ---------------------------------------------------------------------------

def test_provisional_field_is_boolean():
    data = _load_fixture()
    bad = [
        e["id"]
        for e in data
        if not isinstance(e.get("provisional"), bool)
    ]
    assert not bad, (
        f"Entries where provisional is not a bool: {bad[:10]}"
    )


# ---------------------------------------------------------------------------
# 12. Dates are in the future (post 2026-01-01)
# ---------------------------------------------------------------------------

def test_dates_are_in_future_or_recent():
    data = _load_fixture()
    floor = datetime(2026, 1, 1, tzinfo=timezone.utc).date()
    bad = []
    for e in data:
        sd = datetime.strptime(e["start_date"], "%Y-%m-%d").date()
        ed = datetime.strptime(e["end_date"], "%Y-%m-%d").date()
        if sd < floor:
            bad.append((e["id"], "start_date before 2026-01-01", e["start_date"]))
        if ed < sd:
            bad.append((e["id"], "end_date before start_date", e["end_date"]))
    assert not bad, f"Date validation failures: {bad[:10]}"


# ---------------------------------------------------------------------------
# 13. Coverage targets hit (per Part 2 spec)
# ---------------------------------------------------------------------------

def test_coverage_targets_met():
    """Per-event-type counts must meet the minimums defined in the spec."""
    data = _load_fixture()
    counts: dict[str, int] = {}
    for e in data:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    failures = []
    for t, minimum in COVERAGE_TARGETS.items():
        actual = counts.get(t, 0)
        if actual < minimum:
            failures.append((t, minimum, actual))
    assert not failures, (
        f"Coverage targets not met: {failures}\n"
        f"Actual counts: {counts}"
    )


# ---------------------------------------------------------------------------
# 14. F1 races must not be provisional (Jolpica is rock-solid)
# ---------------------------------------------------------------------------

def test_f1_races_are_not_provisional():
    """Jolpica is a structured, authenticated-equal API. F1 entries are
    the highest-confidence entries in the fixture."""
    data = _load_fixture()
    bad = [
        e["id"]
        for e in data
        if e["type"] == "f1_race" and e.get("provisional") is True
    ]
    assert not bad, f"F1 races should not be provisional: {bad}"


# ---------------------------------------------------------------------------
# 15. Generator script exists
# ---------------------------------------------------------------------------

def test_build_script_exists():
    assert SCRIPTS_DIR.joinpath("build_events_fixture.py").exists(), (
        "scripts/build_events_fixture.py must exist (TDD contract)"
    )


# ---------------------------------------------------------------------------
# 16. SOURCES.md exists and has the build metadata header
# ---------------------------------------------------------------------------

def test_sources_md_exists_and_has_header():
    assert SOURCES_MD_PATH.exists(), (
        f"data/SOURCES.md must exist at {SOURCES_MD_PATH}"
    )
    text = SOURCES_MD_PATH.read_text()
    assert text.startswith("# Events Fixture"), (
        "SOURCES.md must start with '# Events Fixture'"
    )
    assert "Built:" in text, "SOURCES.md must record a build timestamp"
    assert "Total events:" in text, "SOURCES.md must record total events"


# ---------------------------------------------------------------------------
# 17. verified_utc is a valid ISO timestamp
# ---------------------------------------------------------------------------

def test_verified_utc_is_iso_timestamp():
    data = _load_fixture()
    iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    bad = [
        (e["id"], e["verified_utc"])
        for e in data
        if not iso_re.match(e.get("verified_utc", ""))
    ]
    assert not bad, f"verified_utc not in ISO Z format: {bad[:5]}"
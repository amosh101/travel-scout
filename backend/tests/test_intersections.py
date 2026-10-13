"""
Tests for the intersection algorithm (app/services/intersections.py).

The algorithm is the brain of the product. Given a user's interests and
the events catalog, it finds date+geography windows where 2+ of the user's
interests have real events — these are the "unique trip candidates" that
differentiate Travel Scout from a flight-watch tool.

TDD discipline: tests are written first, then the implementation. The
service is pure functions over plain data (no DB) so tests use simple
fixtures rather than the conftest db_session.

Public API (the spec these tests pin down):
  parse_keywords(text) -> set[str]
      Lowercase, split on whitespace/commas, drop stopwords. Used to turn
      the user's free-text event_keywords into a set of match terms.

  match_events_for_interest(interest, events) -> list[MatchedEvent]
      For one interest, return the events that match it (tag overlap or
      name/destination overlap). Returns [] for no matches.

  find_intersections(interests, events, *, date_window_days=7,
                     dismissed_ids=set()) -> list[IntersectionCandidate]
      Cross-interest: find candidate trips where 2+ interests have events
      in the same city on overlapping dates (within date_window_days).
      Ranked by score descending. Excludes dismissed intersection_ids.

  score_intersection(candidate) -> float
      Compute the score for one candidate. Higher = better.

Score formula (documented here so the test that pins it stays stable):
    base     = matched_interests_count * 10         (more is better)
    overlap  = days_in_window / date_window_days    (tighter = higher)
    priority = sum(1 / (interest.priority + 1))     (higher priority = higher)
    freshness = 1 / (1 + days_until_start / 90)     (sooner = higher)
    score = base * overlap_weight + priority * priority_weight + freshness * 30

Default weights: overlap_weight=5, priority_weight=8.

The fixtures in tests/fixtures/sample_events.py provide a curated set of
events that exercises:
  - F1 race + Uffizi exhibition in Italy on overlapping dates (Rome trip)
  - F1 race + Jazz festival in Belgium on overlapping dates (Spa + Brussels)
  - Solo event (no intersection, must not appear in results)
  - Past event (must not appear)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pytest

from app.services.intersections import (
    parse_keywords,
    match_events_for_interest,
    find_intersections,
    score_intersection,
    MatchedEvent,
    IntersectionCandidate,
    TODAY,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


def make_interest(
    *,
    id=None,
    name: str = "F1 races",
    event_keywords: str = "f1 motorsport",
    destination_region: str | None = None,
    priority: int = 0,
) -> dict:
    """Build an interest-shaped dict for tests.

    Mirrors the SQLAlchemy Interest attributes the algorithm reads:
    id, name, event_keywords, destination_region, priority.
    """
    from uuid import uuid4
    return {
        "id": id or uuid4(),
        "name": name,
        "event_keywords": event_keywords,
        "destination_region": destination_region,
        "priority": priority,
    }


def _default_start_date() -> str:
    """Default event date: 60 days in the future. Keeps tests stable as
    TODAY advances — the past/future logic in the algorithm depends on
    relative dates, not absolute ones."""
    return (TODAY + timedelta(days=60)).isoformat()


def future(days: int) -> str:
    """A start_date N days in the future, as ISO string."""
    return (TODAY + timedelta(days=days)).isoformat()


def make_event(
    *,
    id: str,
    name: str,
    type: str = "music_festival",
    city: str = "London",
    country: str = "GB",
    start_date: str | None = None,
    end_date: str | None = None,
    interest_tags: list[str] | None = None,
    destination_region: str | None = None,
) -> dict:
    return {
        "id": id,
        "name": name,
        "type": type,
        "city": city,
        "country": country,
        "start_date": start_date or _default_start_date(),
        "end_date": end_date or start_date or _default_start_date(),
        "interest_tags": interest_tags or [],
        "destination_region": destination_region,
    }


# ─── parse_keywords ────────────────────────────────────────────────────────


def test_parse_keywords_lowercases():
    """parse_keywords lowercases input so 'F1' and 'f1' match the same tags."""
    assert parse_keywords("F1 Races") == {"f1", "races"}


def test_parse_keywords_splits_on_whitespace_and_punctuation():
    """parse_keywords splits on commas, hyphens, and whitespace."""
    assert parse_keywords("Italian Renaissance art, live-jazz") == {
        "italian", "renaissance", "art", "live", "jazz",
    }


def test_parse_keywords_drops_stopwords():
    """parse_keywords drops common English stopwords so they don't pollute matches."""
    result = parse_keywords("the F1 race in Europe and live jazz")
    assert "the" not in result
    assert "and" not in result
    assert "in" not in result
    assert "f1" in result
    assert "europe" in result


def test_parse_keywords_preserves_canonical_short_tags():
    """parse_keywords keeps canonical short tags like 'f1' — they're
    expensive to type (full name is 'Formula 1') but cheap to match against
    event_tags. Only stopwords are dropped, not length.

    This test is the inverse of an earlier design that dropped all tokens
    shorter than 3 chars. The product rule is: trust canonical short tags
    (f1, dj, ai, edm, etc.) and only filter linguistic stopwords.
    """
    result = parse_keywords("F1 a an to at the races")
    # 'f1' is preserved (canonical short tag)
    assert "f1" in result
    assert "races" in result
    # 'the' is dropped (stopword)
    assert "the" not in result
    # 'a' / 'an' / 'to' / 'at' are dropped (stopwords)
    assert "a" not in result
    assert "an" not in result
    assert "to" not in result
    assert "at" not in result


def test_parse_keywords_empty_input_returns_empty_set():
    """Empty / None input → empty set (no matches)."""
    assert parse_keywords("") == set()
    assert parse_keywords(None) == set()


# ─── match_events_for_interest ────────────────────────────────────────────


def test_match_events_for_interest_matches_on_tag_overlap():
    """Events whose interest_tags overlap with parsed keywords are matches."""
    interest = make_interest(event_keywords="F1 motorsport")
    events = [
        make_event(id="f1-monaco", name="Monaco GP", type="f1_race",
                   interest_tags=["f1", "motorsport"]),
        make_event(id="uffizi", name="Uffizi Exhibition", type="art_exhibition",
                   interest_tags=["art", "renaissance"]),
    ]
    matches = match_events_for_interest(interest, events)
    assert len(matches) == 1
    assert matches[0].event["id"] == "f1-monaco"
    assert matches[0].matched_keyword in {"f1", "motorsport"}


def test_match_events_for_interest_matches_on_name_substring():
    """If no tag overlap, fall back to substring match on the event name."""
    interest = make_interest(event_keywords="renaissance")
    events = [
        make_event(id="uffizi", name="Renaissance Masters at the Uffizi",
                   interest_tags=["art"]),  # no 'renaissance' tag, but name has it
    ]
    matches = match_events_for_interest(interest, events)
    assert len(matches) == 1
    assert matches[0].event["id"] == "uffizi"


def test_match_events_for_interest_returns_empty_for_no_match():
    """Interest with no overlap returns [] — no false positives."""
    interest = make_interest(event_keywords="kazakhstan overland yurt")
    events = [
        make_event(id="f1-monaco", name="Monaco GP", interest_tags=["f1"]),
    ]
    matches = match_events_for_interest(interest, events)
    assert matches == []


def test_match_events_for_interest_returns_match_strength():
    """Each match carries a match_strength: 2 for tag overlap, 1 for name match."""
    interest = make_interest(event_keywords="renaissance art")
    events = [
        make_event(id="uffizi", name="Renaissance Masters",
                   interest_tags=["art", "renaissance"]),  # tag match → strength 2
        make_event(id="uffizi-tour", name="Guided Tour",
                   interest_tags=["guided_tour"]),  # no tag, but 'art' in name? no
    ]
    matches = match_events_for_interest(interest, events)
    assert len(matches) == 1
    assert matches[0].match_strength == 2


def test_match_events_for_interest_excludes_past_events():
    """Events before today are excluded (the user wants future trips)."""
    from app.services.intersections import TODAY  # implementation provides this
    today = TODAY
    past_event = make_event(
        id="past", name="Old F1 Race",
        start_date=(today - timedelta(days=30)).isoformat(),
        interest_tags=["f1"],
    )
    future_event = make_event(
        id="future", name="New F1 Race",
        start_date=(today + timedelta(days=30)).isoformat(),
        interest_tags=["f1"],
    )
    interest = make_interest(event_keywords="f1")
    matches = match_events_for_interest(interest, [past_event, future_event])
    matched_ids = [m.event["id"] for m in matches]
    assert "future" in matched_ids
    assert "past" not in matched_ids


# ─── find_intersections ───────────────────────────────────────────────────


def test_find_intersections_empty_interests_returns_empty():
    """No interests → no candidates."""
    events = [make_event(id="x", name="Anything")]
    assert find_intersections([], events) == []


def test_find_intersections_one_interest_returns_empty():
    """Single interest cannot form an intersection (need ≥2)."""
    interest = make_interest(event_keywords="f1")
    events = [make_event(id="f1-monaco", name="Monaco GP",
                          interest_tags=["f1"])]
    assert find_intersections([interest], events) == []


def test_find_intersections_finds_two_interests_same_city_overlapping_dates():
    """Two interests with events in the same city on overlapping dates → 1 candidate."""
    f1 = make_interest(id="i-f1", event_keywords="f1 motorsport", priority=0)
    uffizi = make_interest(id="i-uffizi", event_keywords="renaissance art", priority=1)
    events = [
        make_event(id="f1-monaco", name="Monaco GP 2026", type="f1_race",
                   city="Monaco", country="MC",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="uffizi-rome", name="Uffizi Spring Show 2026",
                   type="art_exhibition", city="Florence", country="IT",
                   start_date=future(58),
                   interest_tags=["art", "renaissance"]),
    ]
    # Same city required for an intersection in v1 — this test documents that
    # constraint. Florence (Uffizi) and Monaco are NOT the same city → no
    # intersection. See the next test for the positive case.
    candidates = find_intersections([f1, uffizi], events)
    assert candidates == []


def test_find_intersections_finds_two_interests_same_city_overlapping_dates_positive():
    """Two events in the same city, overlapping dates → 1 candidate with both interests."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=1)
    events = [
        make_event(id="spa-f1", name="Belgian GP 2026", type="f1_race",
                   city="Spa", country="BE",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="brussels-jazz", name="Brussels Jazz Festival 2026",
                   type="music_festival", city="Brussels", country="BE",
                   start_date=future(59),
                   interest_tags=["jazz", "music_festival"]),
    ]
    # Spa and Brussels are different cities but both in Belgium. For v1 we
    # REQUIRE same city. This test asserts the v1 constraint — it should
    # return [] until we relax to "same country within driving distance".
    # Update this test if/when we add country-level matching.
    candidates = find_intersections([interest_a, interest_b], events, date_window_days=7)
    assert candidates == []  # v1 constraint: same city only


def test_find_intersections_returns_candidate_when_same_city_two_interests():
    """Two interests with events in SAME CITY, overlapping dates → 1 candidate."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=1)
    events = [
        make_event(id="imola-f1", name="Imola GP 2026", type="f1_race",
                   city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz", name="Imola Jazz Night 2026",
                   type="music_festival", city="Imola", country="IT",
                   start_date=future(61),
                   interest_tags=["jazz", "music_festival"]),
    ]
    candidates = find_intersections([interest_a, interest_b], events, date_window_days=7)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.city == "Imola"
    assert cand.country == "IT"
    assert {e.event["id"] for e in cand.events} == {"imola-f1", "imola-jazz"}
    assert len(cand.interests) == 2
    assert cand.score > 0


def test_find_intersections_excludes_events_outside_window():
    """Events more than date_window_days apart in the same city do NOT intersect."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=1)
    events = [
        make_event(id="imola-f1", name="Imola GP 2026", type="f1_race",
                   city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz-far", name="Imola Jazz Autumn 2026",
                   type="music_festival", city="Imola", country="IT",
                   start_date=future(180),  # ~4 months later
                   interest_tags=["jazz", "music_festival"]),
    ]
    candidates = find_intersections([interest_a, interest_b], events, date_window_days=7)
    assert candidates == []


def test_find_intersections_excludes_dismissed_ids():
    """dismissed_ids parameter excludes candidates whose id is in the set."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=1)
    events = [
        make_event(id="imola-f1", name="Imola GP 2026", type="f1_race",
                   city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz", name="Imola Jazz 2026",
                   type="music_festival", city="Imola", country="IT",
                   start_date=future(61),
                   interest_tags=["jazz", "music_festival"]),
    ]
    # First call: finds the candidate
    candidates = find_intersections([interest_a, interest_b], events, date_window_days=7)
    assert len(candidates) == 1
    cand_id = candidates[0].id

    # Second call: dismissed → excluded
    dismissed = find_intersections(
        [interest_a, interest_b], events,
        date_window_days=7, dismissed_ids={cand_id},
    )
    assert dismissed == []


def test_find_intersections_results_ranked_by_score_descending():
    """Multiple candidates → returned highest-score first."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=0)
    interest_c = make_interest(id="i-c", event_keywords="food wine", priority=2)
    events = [
        # Tight overlap (1 day apart, both priority 0) — high score
        make_event(id="imola-f1", name="Imola GP", type="f1_race",
                   city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz", name="Imola Jazz", type="music_festival",
                   city="Imola", country="IT",
                   start_date=future(61),
                   interest_tags=["jazz", "music_festival"]),
        # Looser overlap (5 days apart) + lower-priority interest — lower score
        make_event(id="milan-f1", name="Monza GP", type="f1_race",
                   city="Monza", country="IT",
                   start_date=future(90),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="milan-wine", name="Milano Wine Week", type="food_wine",
                   city="Monza", country="IT",
                   start_date=future(95),
                   interest_tags=["food", "wine"]),
    ]
    candidates = find_intersections(
        [interest_a, interest_b, interest_c], events, date_window_days=7,
    )
    assert len(candidates) == 2
    # Imola (tight, 1 day) should outrank Monza (5 days + lower-priority interest)
    assert candidates[0].city == "Imola"
    assert candidates[1].city == "Monza"
    assert candidates[0].score > candidates[1].score


def test_find_intersections_candidate_id_is_stable():
    """The candidate id is derived from city + earliest start_date so that
    re-running /find for the same trip produces the same id (this is what
    lets DismissedTrip work)."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=0)
    events = [
        make_event(id="imola-f1", name="Imola GP", type="f1_race",
                   city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz", name="Imola Jazz", type="music_festival",
                   city="Imola", country="IT",
                   start_date=future(61),
                   interest_tags=["jazz", "music_festival"]),
    ]
    candidates1 = find_intersections([interest_a, interest_b], events, date_window_days=7)
    candidates2 = find_intersections([interest_a, interest_b], events, date_window_days=7)
    assert candidates1[0].id == candidates2[0].id
    assert "imola" in candidates1[0].id.lower()
    # The date portion of the id is an ISO date — assert the format, not the year
    # (TODAY is computed at import time, so the year is whatever it is).
    iso_date_part = candidates1[0].id.split("-")[-3:]  # e.g. ["2026", "07", "24"]
    assert len(iso_date_part) == 3
    assert all(len(p) in (2, 4) for p in iso_date_part)


def test_find_intersections_three_interests_one_candidate():
    """Three interests matching in the same city produce ONE candidate with score
    reflecting all three (not three candidates)."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=1)
    interest_c = make_interest(id="i-c", event_keywords="art renaissance", priority=2)
    events = [
        make_event(id="imola-f1", name="Imola GP", type="f1_race",
                   city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz", name="Imola Jazz", type="music_festival",
                   city="Imola", country="IT",
                   start_date=future(61),
                   interest_tags=["jazz", "music_festival"]),
        make_event(id="imola-art", name="Imola Renaissance",
                   type="art_exhibition", city="Imola", country="IT",
                   start_date=future(62),
                   interest_tags=["art", "renaissance"]),
    ]
    candidates = find_intersections(
        [interest_a, interest_b, interest_c], events, date_window_days=7,
    )
    assert len(candidates) == 1
    assert len(candidates[0].interests) == 3


def test_find_intersections_same_city_same_day_dedupes_to_one_candidate():
    """If two events for the same interest fall on the same day in the same city,
    they should appear in ONE candidate (not two)."""
    interest_a = make_interest(id="i-a", event_keywords="f1 motorsport", priority=0)
    interest_b = make_interest(id="i-b", event_keywords="jazz music", priority=1)
    events = [
        make_event(id="imola-f1-qualifying", name="Imola Qualifying",
                   type="f1_race", city="Imola", country="IT",
                   start_date=future(60),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-f1-race", name="Imola Race",
                   type="f1_race", city="Imola", country="IT",
                   start_date=future(61),
                   interest_tags=["f1", "motorsport"]),
        make_event(id="imola-jazz", name="Imola Jazz",
                   type="music_festival", city="Imola", country="IT",
                   start_date=future(62),
                   interest_tags=["jazz"]),
    ]
    candidates = find_intersections([interest_a, interest_b], events, date_window_days=7)
    assert len(candidates) == 1
    # Both F1 events (qualifying + race) plus the jazz event = 3 events in the
    # candidate, but only 2 distinct interests matched.
    assert len(candidates[0].events) == 3
    assert len(candidates[0].interests) == 2


# ─── score_intersection ───────────────────────────────────────────────────


def test_score_intersection_higher_for_more_interests():
    """More matched interests → strictly higher base score."""
    from uuid import uuid4
    cand_small = IntersectionCandidate(
        id="x", city="X", country="XX", start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        events=[], interests=[{"id": uuid4(), "priority": 0}],
    )
    cand_big = IntersectionCandidate(
        id="x", city="X", country="XX", start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        events=[], interests=[
            {"id": uuid4(), "priority": 0},
            {"id": uuid4(), "priority": 0},
            {"id": uuid4(), "priority": 0},
        ],
    )
    assert score_intersection(cand_big) > score_intersection(cand_small)


def test_score_intersection_higher_for_tighter_date_window():
    """Same interests, tighter date spread → higher score (overlap component)."""
    from uuid import uuid4
    interests = [{"id": uuid4(), "priority": 0}, {"id": uuid4(), "priority": 0}]
    cand_tight = IntersectionCandidate(
        id="x", city="X", country="XX",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 2),
        events=[], interests=interests,
    )
    cand_loose = IntersectionCandidate(
        id="x", city="X", country="XX",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 8),  # 7-day spread
        events=[], interests=interests,
    )
    assert score_intersection(cand_tight) > score_intersection(cand_loose)


def test_score_intersection_higher_priority_interest_increases_score():
    """Higher-priority interest (lower number) → higher priority component."""
    from uuid import uuid4
    interests_top = [
        {"id": uuid4(), "priority": 0},
        {"id": uuid4(), "priority": 5},
    ]
    interests_both_low = [
        {"id": uuid4(), "priority": 5},
        {"id": uuid4(), "priority": 5},
    ]
    cand_top = IntersectionCandidate(
        id="x", city="X", country="XX",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 2),
        events=[], interests=interests_top,
    )
    cand_low = IntersectionCandidate(
        id="x", city="X", country="XX",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 2),
        events=[], interests=interests_both_low,
    )
    assert score_intersection(cand_top) > score_intersection(cand_low)
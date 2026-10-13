"""
The intersection algorithm — the brain of Travel Scout.

Given a user's interests and the events catalog, find date+geography
windows where 2+ of the user's interests have real events. These are the
"unique trip candidates" that differentiate Travel Scout from a
flight-watch tool.

Design constraints (locked in by tests/test_intersections.py):
  - Pure functions, no DB. Inputs are plain dicts/lists; outputs are
    dataclasses the router layer can serialize.
  - Same-city v1: two events only form an intersection if they're in
    the same city. (Country-level matching with driving-distance radius
    is a v2 feature — see the v1-constraint tests for the placeholder.)
  - Stable candidate id: derived from `city + earliest_start_date` so
    re-running /find produces the same id, which lets DismissedTrip
    persist across requests.
  - Past events excluded.
  - Dismissed intersection_ids excluded.

Score formula (documented in the module docstring of the test file):
    base      = matched_interests_count * 10
    overlap   = 1 / (1 + window_days / date_window_days)
    priority  = sum(1 / (interest.priority + 1))
    freshness = 1 / (1 + days_until_start / 90)
    score = base * 5
          + priority * 8
          + freshness * 30
          + overlap * 5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

# `TODAY` is module-level so tests can pin "future" / "past" relative
# to a known reference. Tests import it directly.
TODAY = date.today()


# Stopwords dropped from parsed keywords. Curated for the English-language
# use case; expand if the product localizes.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for",
    "from", "has", "have", "in", "is", "it", "its", "of", "on", "or",
    "that", "the", "this", "to", "was", "were", "will", "with",
})

# Tokens shorter than this are dropped. Set to 1 so canonical short tags
# like 'f1' are preserved — they're expensive to type but cheap to match
# against event_tags. The 'the' / 'a' / 'and' stopwords are still dropped
# via _STOPWORDS below.
_MIN_KEYWORD_LENGTH = 1


@dataclass(frozen=True)
class MatchedEvent:
    """One event that matched one interest, with provenance.

    Attributes:
        event: the event dict (id, name, dates, tags, etc).
        matched_interest: the interest dict that produced this match.
        matched_keyword: the specific keyword (from parsed event_keywords)
            that matched. Useful for showing the user *why* an event was
            included in the intersection.
        match_strength: 2 for tag overlap, 1 for name substring match.
            Higher = stronger signal.
    """
    event: dict
    matched_interest: dict
    matched_keyword: str
    match_strength: int


@dataclass
class IntersectionCandidate:
    """One unique trip candidate: events from ≥2 interests overlapping
    in the same city within `date_window_days`.

    Attributes:
        id: stable identifier, "<city-slug>-<YYYY-MM-DD>" based on the
            earliest event's start_date. Same trip → same id across runs.
        city: the city where the events cluster.
        country: ISO 3166-1 alpha-2 country code.
        start_date: earliest event start_date in the cluster.
        end_date: latest event end_date in the cluster.
        events: the MatchedEvents that form this intersection.
        interests: distinct interests that produced these matches
            (deduped by id).
        score: numeric ranking — higher = better.
        score_breakdown: dict of component scores for transparency
            (so the UI can show "Why this trip?").
    """
    id: str
    city: str
    country: str
    start_date: date
    end_date: date
    events: list[MatchedEvent] = field(default_factory=list)
    interests: list[dict] = field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict = field(default_factory=dict)


# ─── Public API ────────────────────────────────────────────────────────────


def parse_keywords(text: str | None) -> set[str]:
    """Lowercase, split on whitespace/commas/hyphens, drop stopwords.

    Returns a set of normalized keyword tokens. Empty / None → empty set.
    """
    if not text:
        return set()
    # Replace punctuation with spaces, then split on whitespace.
    normalized = text.lower()
    for ch in ",;/-—_":
        normalized = normalized.replace(ch, " ")
    tokens = normalized.split()
    return {
        t for t in tokens
        if len(t) >= _MIN_KEYWORD_LENGTH and t not in _STOPWORDS
    }


def match_events_for_interest(
    interest: dict,
    events: Iterable[dict],
) -> list[MatchedEvent]:
    """Return events that match this interest's keywords.

    Two match paths, in priority order:
      1. Tag overlap (match_strength=2): the parsed keyword is in the
         event's interest_tags list.
      2. Name / destination_region substring (match_strength=1): the
         keyword appears as a substring of the event's name or
         destination_region.

    Past events (start_date < TODAY) are excluded.
    """
    keywords = parse_keywords(interest.get("event_keywords"))
    if not keywords:
        return []

    matches: list[MatchedEvent] = []
    seen_event_ids: set[str] = set()

    for event in events:
        event_id = event.get("id")
        if event_id in seen_event_ids:
            continue  # one match per event per interest is enough

        # Exclude past events
        event_date = _parse_event_date(event.get("start_date"))
        if event_date is None or event_date < TODAY:
            continue

        # Path 1: tag overlap
        tags = {t.lower() for t in event.get("interest_tags", [])}
        tag_hit = keywords & tags
        if tag_hit:
            # Prefer the most-specific keyword (longest) for the explanation
            kw = max(tag_hit, key=len)
            matches.append(MatchedEvent(
                event=event,
                matched_interest=interest,
                matched_keyword=kw,
                match_strength=2,
            ))
            seen_event_ids.add(event_id)
            continue

        # Path 2: name / destination_region substring
        name = (event.get("name") or "").lower()
        region = (event.get("destination_region") or "").lower()
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in name or kw in region:
                matches.append(MatchedEvent(
                    event=event,
                    matched_interest=interest,
                    matched_keyword=kw,
                    match_strength=1,
                ))
                seen_event_ids.add(event_id)
                break

    return matches


def find_intersections(
    interests: Iterable[dict],
    events: Iterable[dict],
    *,
    date_window_days: int = 7,
    dismissed_ids: set[str] | None = None,
) -> list[IntersectionCandidate]:
    """Find candidates where ≥2 interests have events in the same city
    on overlapping dates (within `date_window_days`).

    Returns candidates sorted by score (descending). Excludes dismissed ids.
    """
    dismissed_ids = dismissed_ids or set()
    events_list = list(events)
    interests_list = list(interests)

    if len(interests_list) < 2:
        return []

    # 1. For each interest, compute its matched events.
    matches_by_interest: dict[str, list[MatchedEvent]] = {}
    for interest in interests_list:
        iid = str(interest.get("id"))
        matches_by_interest[iid] = match_events_for_interest(interest, events_list)

    # 2. Group matches by city.
    matches_by_city: dict[tuple[str, str], list[MatchedEvent]] = {}
    for interest in interests_list:
        iid = str(interest.get("id"))
        for m in matches_by_interest.get(iid, []):
            city = m.event.get("city", "")
            country = m.event.get("country", "")
            if not city:
                continue
            matches_by_city.setdefault((city, country), []).append(m)

    # 3. For each city, find date-window clusters where ≥2 interests overlap.
    candidates: list[IntersectionCandidate] = []
    for (city, country), city_matches in matches_by_city.items():
        # Collect distinct interests in this city
        distinct_interest_ids = {
            str(m.matched_interest.get("id")) for m in city_matches
        }
        if len(distinct_interest_ids) < 2:
            continue

        # Sort matches by start_date so we cluster them chronologically.
        sorted_matches = sorted(
            city_matches,
            key=lambda m: (_parse_event_date(m.event.get("start_date")) or TODAY),
        )

        # Greedy sliding-window cluster: start a window at the first event;
        # add events while their date is within date_window_days of the
        # window's earliest start_date. If we still have ≥2 interests in
        # the window, emit a candidate. Then start a new window at the next
        # event after the current window's end.
        i = 0
        while i < len(sorted_matches):
            window_start_event = sorted_matches[i]
            window_start_date = _parse_event_date(
                window_start_event.event.get("start_date")
            ) or TODAY
            window_end_date = window_start_date

            window: list[MatchedEvent] = [window_start_event]
            j = i + 1
            while j < len(sorted_matches):
                next_date = _parse_event_date(
                    sorted_matches[j].event.get("start_date")
                ) or TODAY
                if (next_date - window_start_date).days <= date_window_days:
                    window.append(sorted_matches[j])
                    if next_date > window_end_date:
                        window_end_date = next_date
                    j += 1
                else:
                    break

            # Distinct interests in window
            window_interest_ids = {
                str(m.matched_interest.get("id")) for m in window
            }
            if len(window_interest_ids) >= 2:
                # Resolve the interest dicts (preserving order)
                interest_dicts = []
                seen_iids = set()
                for m in window:
                    iid = str(m.matched_interest.get("id"))
                    if iid not in seen_iids:
                        seen_iids.add(iid)
                        interest_dicts.append(m.matched_interest)

                # Compute candidate's overall end_date as max(end_date of events)
                event_end_dates = [
                    _parse_event_date(m.event.get("end_date"))
                    or _parse_event_date(m.event.get("start_date"))
                    or TODAY
                    for m in window
                ]
                cluster_end_date = max(event_end_dates)

                cand = IntersectionCandidate(
                    id=_make_candidate_id(city, window_start_date),
                    city=city,
                    country=country,
                    start_date=window_start_date,
                    end_date=cluster_end_date,
                    events=window,
                    interests=interest_dicts,
                )
                cand.score, cand.score_breakdown = _score(
                    cand, date_window_days=date_window_days,
                )
                if cand.id not in dismissed_ids:
                    candidates.append(cand)

            i = j if j > i else i + 1

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


def score_intersection(candidate: IntersectionCandidate) -> float:
    """Compute the score for one candidate. Public so the router layer
    can re-score after the user updates priorities."""
    score, _ = _score(candidate)
    return score


# ─── Internals ─────────────────────────────────────────────────────────────


def _parse_event_date(value) -> date | None:
    """Parse a date string in ISO format (YYYY-MM-DD). Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _make_candidate_id(city: str, start_date: date) -> str:
    """Stable, slug-based candidate id: lower(city-with-dashes)-YYYY-MM-DD.

    Two runs of /find on the same events produce the same id, which lets
    DismissedTrip work across requests.
    """
    slug = "".join(c if c.isalnum() else "-" for c in city.lower()).strip("-")
    return f"{slug}-{start_date.isoformat()}"


def _score(
    candidate: IntersectionCandidate,
    *,
    date_window_days: int = 7,
) -> tuple[float, dict]:
    """Compute the score and a breakdown dict for transparency."""
    interests = candidate.interests
    window_days = max((candidate.end_date - candidate.start_date).days, 0)
    days_until_start = max((candidate.start_date - TODAY).days, 0)

    base = len(interests) * 10.0
    overlap = 1.0 / (1.0 + window_days / max(date_window_days, 1))
    priority = sum(1.0 / (i.get("priority", 5) + 1) for i in interests)
    freshness = 1.0 / (1.0 + days_until_start / 90.0)

    # Weighted sum. Weights locked in by tests — keep stable.
    score = (
        base * 5.0
        + priority * 8.0
        + freshness * 30.0
        + overlap * 5.0
    )

    breakdown = {
        "base": base,
        "overlap": overlap,
        "priority": priority,
        "freshness": freshness,
        "window_days": window_days,
        "days_until_start": days_until_start,
    }
    return score, breakdown
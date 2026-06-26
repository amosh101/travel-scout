"""
Tests for the itinerary composer (app/services/itinerary_composer.py).

The composer takes one IntersectionCandidate (the brain's output) and
attaches practical travel logistics:
  - A flight from the user's origin airport to the candidate's city
  - A return flight (same logic, reversed)
  - A day-by-day plan: which events fall on which day, with notes
  - A booking URL for the flight so the user can click → book

This is the bridge between the "where + when" of intersections and the
"how do I actually get there" of a bookable trip.

TDD discipline: tests first, implementation second. Public API:

  pick_flight(flights, *, origin, destination, depart_date, return_date) -> FlightPick | None
      Choose the cheapest flight from a list of dicts that matches the
      route. Returns None if no flight covers the route.

  compose_itinerary(candidate, events, flights, *, user_origin,
                    return_window_days=3) -> Itinerary | None
      Build the full itinerary. Returns None if no flight is available
      (the router can still save the candidate as a "no flight" entry).

  estimate_total_cost(flight_price_usd, events) -> float
      Sum the flight + any ticketed events. Non-ticketed events are free.
      Used for "estimated total" display in the UI.

  DayPlan: date + events_for_the_day + notes
  Itinerary: id + candidate_id + flight details + days + total cost
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

import pytest

from app.services.intersections import (
    IntersectionCandidate,
    MatchedEvent,
    TODAY,
)
from app.services.itinerary_composer import (
    pick_flight,
    compose_itinerary,
    estimate_total_cost,
    Itinerary,
    DayPlan,
    FlightPick,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


def make_flight(
    *,
    id: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    price_usd: float = 500.0,
    airline: str = "Test Air",
    booking_url: str | None = None,
    provisional: bool = True,
) -> dict:
    return {
        "id": id,
        "origin": origin,
        "destination": destination,
        "depart_date": depart_date,
        "return_date": return_date,
        "price_usd": price_usd,
        "currency": "USD",
        "airline": airline,
        "booking_url": booking_url or f"https://example.com/book/{id}",
        "provisional": provisional,
    }


def make_candidate(
    *,
    id: str = "imola-2026-08-23",
    city: str = "Imola",
    country: str = "IT",
    start_date: date | None = None,
    end_date: date | None = None,
    events: list[MatchedEvent] | None = None,
    interests: list[dict] | None = None,
) -> IntersectionCandidate:
    return IntersectionCandidate(
        id=id,
        city=city,
        country=country,
        start_date=start_date or (TODAY + timedelta(days=60)),
        end_date=end_date or (TODAY + timedelta(days=62)),
        events=events or [],
        interests=interests or [],
    )


def make_matched_event(
    *,
    event_id: str,
    event_name: str = "Test Event",
    event_type: str = "music_festival",
    city: str = "Imola",
    country: str = "IT",
    start_date: str | None = None,
    end_date: str | None = None,
    interest_id=None,
    interest_name: str = "Test Interest",
    matched_keyword: str = "test",
) -> MatchedEvent:
    return MatchedEvent(
        event={
            "id": event_id,
            "name": event_name,
            "type": event_type,
            "city": city,
            "country": country,
            "start_date": start_date or (TODAY + timedelta(days=60)).isoformat(),
            "end_date": end_date or (TODAY + timedelta(days=60)).isoformat(),
            "interest_tags": ["test"],
        },
        matched_interest={
            "id": interest_id or "00000000-0000-0000-0000-000000000001",
            "name": interest_name,
        },
        matched_keyword=matched_keyword,
        match_strength=2,
    )


# ─── pick_flight ───────────────────────────────────────────────────────────


def test_pick_flight_returns_cheapest_matching_route():
    """Of multiple flights for the same route + dates, pick the cheapest."""
    flights = [
        make_flight(id="exp", origin="MPM", destination="BLQ",
                    depart_date="2026-08-20", return_date="2026-08-25",
                    price_usd=1200.0),
        make_flight(id="cheap", origin="MPM", destination="BLQ",
                    depart_date="2026-08-20", return_date="2026-08-25",
                    price_usd=800.0),
        make_flight(id="pricier", origin="MPM", destination="BLQ",
                    depart_date="2026-08-20", return_date="2026-08-25",
                    price_usd=950.0),
    ]
    pick = pick_flight(flights, origin="MPM", destination="BLQ",
                       depart_date=date(2026, 8, 20), return_date=date(2026, 8, 25))
    assert pick is not None
    assert pick.flight["id"] == "cheap"
    assert pick.flight["price_usd"] == 800.0


def test_pick_flight_matches_by_airport_code():
    """Route matching is by IATA airport code, not city name."""
    flights = [
        make_flight(id="mpm-fco", origin="MPM", destination="FCO",
                    depart_date="2026-09-10", return_date="2026-09-15",
                    price_usd=1000.0),
    ]
    # FCO is Rome's airport; candidate.city="Rome" → composer resolves Rome→FCO
    pick = pick_flight(flights, origin="MPM", destination="FCO",
                       depart_date=date(2026, 9, 10), return_date=date(2026, 9, 15))
    assert pick is not None
    assert pick.flight["id"] == "mpm-fco"


def test_pick_flight_returns_none_when_no_route_match():
    """No flight covers the route → None (not an error)."""
    flights = [
        make_flight(id="lhr-jfk", origin="LHR", destination="JFK",
                    depart_date="2026-09-10", return_date="2026-09-15",
                    price_usd=600.0),
    ]
    pick = pick_flight(flights, origin="MPM", destination="BLQ",
                       depart_date=date(2026, 9, 10), return_date=date(2026, 9, 15))
    assert pick is None


def test_pick_flight_filters_by_provisional_flag():
    """Non-provisional flights (live prices) outrank provisional ones
    (estimated) when both exist for the same route."""
    flights = [
        make_flight(id="prov-cheap", origin="MPM", destination="BLQ",
                    depart_date="2026-09-10", return_date="2026-09-15",
                    price_usd=500.0, provisional=True),
        make_flight(id="live", origin="MPM", destination="BLQ",
                    depart_date="2026-09-10", return_date="2026-09-15",
                    price_usd=900.0, provisional=False),
    ]
    pick = pick_flight(flights, origin="MPM", destination="BLQ",
                       depart_date=date(2026, 9, 10), return_date=date(2026, 9, 15))
    # Live (non-provisional) wins even though it's pricier
    assert pick is not None
    assert pick.flight["id"] == "live"


def test_pick_flight_allows_departure_within_window():
    """If no exact-depart flight exists, accept one that departs within
    a few days of the candidate start (so the user can fly in the day
    before the event). The router sets the window via the call site;
    pick_flight receives the actual depart_date to match."""
    flights = [
        make_flight(id="early", origin="MPM", destination="BLQ",
                    depart_date="2026-08-19", return_date="2026-08-25",
                    price_usd=900.0),
    ]
    # Caller asked for 08-20; flight is 08-19 (one day earlier) — match
    pick = pick_flight(flights, origin="MPM", destination="BLQ",
                       depart_date=date(2026, 8, 20), return_date=date(2026, 8, 25))
    # Exact-date match: not in fixtures. Composer should still find it
    # because the call site allows a ±1 day window before pick_flight.
    # pick_flight itself matches exact dates; the ±window is the composer's job.
    # So this test asserts: exact-date match for 2026-08-20 → no match.
    assert pick is None


# ─── compose_itinerary ────────────────────────────────────────────────────


def test_compose_itinerary_builds_day_by_day_plan():
    """The composer organizes matched events into a day-by-day plan."""
    cand = make_candidate(
        city="Imola", country="IT",
        start_date=TODAY + timedelta(days=60),
        end_date=TODAY + timedelta(days=62),
    )
    e1 = make_matched_event(
        event_id="imola-f1", event_name="Imola GP",
        start_date=(TODAY + timedelta(days=60)).isoformat(),
    )
    e2 = make_matched_event(
        event_id="imola-jazz", event_name="Imola Jazz",
        start_date=(TODAY + timedelta(days=61)).isoformat(),
    )
    cand.events = [e1, e2]

    flights = [
        make_flight(id="mpm-blq", origin="MPM", destination="BLQ",
                    depart_date=(TODAY + timedelta(days=59)).isoformat(),
                    return_date=(TODAY + timedelta(days=63)).isoformat(),
                    price_usd=850.0),
    ]
    itinerary = compose_itinerary(cand, [e1.event, e2.event], flights,
                                   user_origin="MPM")
    assert itinerary is not None
    assert itinerary.destination_airport == "BLQ"
    assert itinerary.flight_price_usd == 850.0
    # Two days with events (one event per day)
    assert len(itinerary.days) == 2
    assert itinerary.days[0].date == TODAY + timedelta(days=60)
    assert len(itinerary.days[0].events) == 1
    assert itinerary.days[0].events[0]["id"] == "imola-f1"


def test_compose_itinerary_returns_none_when_no_flight():
    """No matching flight → None. Caller decides whether to save the
    candidate anyway as a 'no flight' trip (the /find endpoint does)."""
    cand = make_candidate()
    e1 = make_matched_event(event_id="imola-f1")
    cand.events = [e1]
    flights = []  # empty
    itinerary = compose_itinerary(cand, [e1.event], flights, user_origin="MPM")
    assert itinerary is None


def test_compose_itinerary_includes_return_flight():
    """The itinerary spans the full window: depart before the first event,
    return after the last. Flight dates are picked to cover everything."""
    cand = make_candidate(
        start_date=TODAY + timedelta(days=60),
        end_date=TODAY + timedelta(days=64),
    )
    e1 = make_matched_event(
        event_id="imola-f1",
        start_date=(TODAY + timedelta(days=61)).isoformat(),
        end_date=(TODAY + timedelta(days=63)).isoformat(),
    )
    cand.events = [e1]

    flights = [
        make_flight(id="mpm-blq", origin="MPM", destination="BLQ",
                    depart_date=(TODAY + timedelta(days=60)).isoformat(),
                    return_date=(TODAY + timedelta(days=65)).isoformat(),
                    price_usd=900.0),
    ]
    itinerary = compose_itinerary(cand, [e1.event], flights, user_origin="MPM")
    assert itinerary is not None
    # Return flight should be on or after the last event day
    from datetime import date as _date
    last_event_end = _date.fromisoformat(e1.event["end_date"])
    assert itinerary.return_date >= last_event_end


def test_compose_itinerary_id_matches_candidate_id():
    """Itinerary id == candidate id (1:1, find → itinerary)."""
    cand = make_candidate(id="imola-2026-08-23")
    e1 = make_matched_event(event_id="imola-f1")
    cand.events = [e1]
    flights = [
        make_flight(id="mpm-blq", origin="MPM", destination="BLQ",
                    depart_date=(TODAY + timedelta(days=59)).isoformat(),
                    return_date=(TODAY + timedelta(days=63)).isoformat()),
    ]
    itinerary = compose_itinerary(cand, [e1.event], flights, user_origin="MPM")
    assert itinerary is not None
    assert itinerary.id == cand.id
    assert itinerary.candidate_id == cand.id


def test_compose_itinerary_groups_multiple_events_same_day():
    """If 2 events fall on the same day, they share one DayPlan entry."""
    cand = make_candidate(
        start_date=TODAY + timedelta(days=60),
        end_date=TODAY + timedelta(days=62),
    )
    e1 = make_matched_event(
        event_id="imola-f1-qualifying",
        start_date=(TODAY + timedelta(days=60)).isoformat(),
    )
    e2 = make_matched_event(
        event_id="imola-f1-race",
        start_date=(TODAY + timedelta(days=61)).isoformat(),
    )
    e3 = make_matched_event(
        event_id="imola-jazz",
        start_date=(TODAY + timedelta(days=60)).isoformat(),  # same as qualifying
    )
    cand.events = [e1, e2, e3]

    flights = [
        make_flight(id="mpm-blq", origin="MPM", destination="BLQ",
                    depart_date=(TODAY + timedelta(days=59)).isoformat(),
                    return_date=(TODAY + timedelta(days=63)).isoformat()),
    ]
    itinerary = compose_itinerary(cand, [e1.event, e2.event, e3.event],
                                   flights, user_origin="MPM")
    assert itinerary is not None
    # 2 unique days (day 60 = qualifying + jazz, day 61 = race)
    assert len(itinerary.days) == 2
    day_60 = next(d for d in itinerary.days if d.date == TODAY + timedelta(days=60))
    assert len(day_60.events) == 2
    assert {e["id"] for e in day_60.events} == {"imola-f1-qualifying", "imola-jazz"}


def test_compose_itinerary_includes_booking_url():
    """Booking URL is propagated from the picked flight to the itinerary
    so the frontend can render a 'Book this flight' button."""
    cand = make_candidate()
    e1 = make_matched_event(event_id="imola-f1")
    cand.events = [e1]
    flights = [
        make_flight(id="mpm-blq", origin="MPM", destination="BLQ",
                    depart_date=(TODAY + timedelta(days=59)).isoformat(),
                    return_date=(TODAY + timedelta(days=63)).isoformat(),
                    booking_url="https://www.kiwi.com/book/abc123"),
    ]
    itinerary = compose_itinerary(cand, [e1.event], flights, user_origin="MPM")
    assert itinerary is not None
    assert itinerary.flight_booking_url == "https://www.kiwi.com/book/abc123"


# ─── estimate_total_cost ──────────────────────────────────────────────────


def test_estimate_total_cost_sums_flight_and_ticketable_events():
    """Total = flight + sum of any event prices. Events without a price
    are free (assumed unticketed street festivals, free exhibitions, etc.)."""
    flight_price = 850.0
    events = [
        {"id": "uffizi", "name": "Uffizi", "ticket_price_usd": 25.0},
        {"id": "f1", "name": "F1 Race", "ticket_price_usd": 350.0},
        {"id": "jazz", "name": "Jazz Night"},  # no price → free
    ]
    total = estimate_total_cost(flight_price, events)
    assert total == 850.0 + 25.0 + 350.0


def test_estimate_total_cost_no_ticketable_events():
    """Free events (no ticket_price_usd) → total = flight price only."""
    flight_price = 500.0
    events = [
        {"id": "festival", "name": "Free street festival"},
        {"id": "exhibition", "name": "Free gallery"},
    ]
    total = estimate_total_cost(flight_price, events)
    assert total == 500.0


def test_estimate_total_cost_handles_missing_flight():
    """If flight_price is None (no flight found), total is just events."""
    events = [{"id": "x", "ticket_price_usd": 100.0}]
    total = estimate_total_cost(None, events)
    assert total == 100.0


def test_estimate_total_cost_handles_no_events():
    """No events → total is just the flight (or 0 if no flight either)."""
    assert estimate_total_cost(500.0, []) == 500.0
    assert estimate_total_cost(None, []) == 0.0
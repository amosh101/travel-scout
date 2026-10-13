"""
The itinerary composer — bridges the intersection algorithm's "where + when"
with practical travel logistics ("how do I get there, what does it cost").

Given one IntersectionCandidate, the composer:
  1. Resolves the candidate's city to the nearest commercial airport
     (city → IATA code map; small but covers our fixture data).
  2. Picks the cheapest flight that covers the route (live price beats
     provisional estimate when both exist).
  3. Organizes matched events into a day-by-day plan (multiple events on
     the same day share one DayPlan entry).
  4. Estimates total cost: flight + any ticketed events.
  5. Returns None if no flight is available — the caller decides whether
     to save the candidate as a 'no flight' entry.

Design constraints (locked in by tests/test_itinerary_composer.py):
  - Pure functions, no DB.
  - City→airport resolution uses a static dict (small enough; expand
    as the catalog grows). Unknown cities → None → composer returns None.
  - Flight pick: live prices outrank provisional at equal price; among
    same-tier flights, cheapest wins. The router sets the depart_date
    to a small window before the first event so we can fly in early.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from app.services.intersections import IntersectionCandidate, MatchedEvent


# ─── Public data structures ────────────────────────────────────────────────


@dataclass
class FlightPick:
    """One chosen flight, with provenance.

    Attributes:
        flight: the flight dict (id, price, dates, etc).
        score: lower is better. Live (non-provisional) flights get a
            huge discount so they always beat provisional. Among same
            tier, cheaper wins. Used for tests + ranking if extended.
    """
    flight: dict
    score: float


@dataclass
class DayPlan:
    """One day in the itinerary.

    Attributes:
        date: the calendar day.
        events: the events happening on this day (1+ — multiple events
            on the same day share one DayPlan).
        notes: optional human-readable notes ("Day 1: F1 qualifying +
            check into hotel near Imola circuit").
    """
    date: date
    events: list[dict] = field(default_factory=list)
    notes: str = ""


@dataclass
class Itinerary:
    """A complete, bookable trip plan.

    Attributes:
        id: same as the source IntersectionCandidate.id (1:1 mapping).
        candidate_id: the source candidate's id (kept for traceability).
        origin: user's origin airport (IATA).
        destination_airport: IATA code of the airport serving the
            candidate's city.
        destination_city: human-readable city name.
        destination_country: ISO alpha-2 country code.
        depart_date: outbound flight date.
        return_date: inbound flight date.
        flight_price_usd: picked flight's price.
        flight_booking_url: clicked → book on the airline / OTA.
        flight_id: the picked flight's id.
        days: DayPlan entries, one per unique day with at least one event.
        est_total_cost_usd: flight + sum of ticketed events.
    """
    id: str
    candidate_id: str
    origin: str
    destination_airport: str
    destination_city: str
    destination_country: str
    depart_date: date
    return_date: date
    flight_price_usd: float
    flight_booking_url: str
    flight_id: str
    days: list[DayPlan] = field(default_factory=list)
    est_total_cost_usd: float = 0.0


# ─── City → airport map ────────────────────────────────────────────────────
# Curated for the events.json fixture. Add cities as the catalog grows.
# The airport chosen is the one real travelers use to access the city —
# usually the closest major hub, sometimes the city's own if it has one.
_CITY_TO_AIRPORT: dict[str, str] = {
    # Italy
    "imola": "BLQ",        # Bologna
    "monza": "MXP",        # Milan Malpensa
    "milan": "MXP",
    "florence": "FLR",
    "rome": "FCO",
    "venice": "VCE",
    "milan": "MXP",
    "turin": "TRN",
    "verona": "VRN",
    "parma": "PMF",
    "bologna": "BLQ",
    "palermo": "PMO",
    "cagliari": "CAG",
    # Spain
    "barcelona": "BCN",
    "madrid": "MAD",
    "seville": "SVQ",
    "valencia": "VLC",
    "ibiza": "IBZ",
    "mallorca": "PMI",
    "pamplona": "PNA",
    # France
    "paris": "CDG",
    "nice": "NCE",
    "monaco": "NCE",       # Nice is the gateway to Monaco
    "lyon": "LYS",
    "marseille": "MRS",
    "cannes": "NCE",
    # UK
    "london": "LHR",
    "edinburgh": "EDI",
    "manchester": "MAN",
    "liverpool": "LPL",
    "silverstone": "LHR",  # near London
    # Germany / Austria / Switzerland
    "munich": "MUC",
    "berlin": "BER",
    "frankfurt": "FRA",
    "hamburg": "HAM",
    "vienna": "VIE",
    "salzburg": "SZG",
    "innsbruck": "INN",
    "geneva": "GVA",
    "zurich": "ZRH",
    "lucerne": "ZRH",
    "zermatt": "GVA",
    "montreux": "GVA",
    "verbier": "GVA",
    "davos": "ZRH",
    "st moritz": "ZRH",
    # Belgium / Netherlands
    "spa": "LGG",          # Liège is closer than Brussels for Spa-Francorchamps
    "brussels": "BRU",
    "antwerp": "ANR",
    "amsterdam": "AMS",
    "rotterdam": "RTM",
    # Portugal
    "lisbon": "LIS",
    "porto": "OPO",
    # Hungary / Czech / Poland
    "budapest": "BUD",
    "prague": "PRG",
    "krakow": "KRK",
    # Greece / Turkey
    "athens": "ATH",
    "santorini": "JTR",
    "mykonos": "JMK",
    "istanbul": "IST",
    # USA
    "miami": "MIA",
    "new york": "JFK",
    "los angeles": "LAX",
    "austin": "AUS",
    "las vegas": "LAS",
    "indianapolis": "IND",
    "cota": "AUS",         # Circuit of the Americas
    # Australia / Asia
    "melbourne": "MEL",
    "sydney": "SYD",
    "singapore": "SIN",
    "tokyo": "NRT",
    "shanghai": "PVG",
    "suzuka": "NGO",       # nearest to Suzuka circuit
    "shanghai circuit": "PVG",
    "bahrain": "BAH",
    "jeddah": "JED",
    "lusail": "DOH",       # Qatar
    "abu dhabi": "AUH",
    "baku": "GYD",
    "sao paulo": "GRU",
    "mexico city": "MEX",
    "montréal": "YUL",
    "lasalle": "YUL",
}


def resolve_airport(city: str) -> Optional[str]:
    """Resolve a city name to its IATA airport code.

    Returns None if the city isn't in the map. Lookup is case-insensitive.
    """
    if not city:
        return None
    return _CITY_TO_AIRPORT.get(city.lower().strip())


# ─── Public API ────────────────────────────────────────────────────────────


def pick_flight(
    flights: Iterable[dict],
    *,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date,
) -> Optional[FlightPick]:
    """Pick the best flight for the route + dates.

    Selection rule (locked in by tests):
      - Must match origin AND destination (IATA codes).
      - Non-provisional (live price) outranks provisional at equal price.
      - Among same tier, cheapest wins.

    Note: pick_flight matches exact dates. The composer widens the
    depart window to ±1 day before calling pick_flight (so the user can
    fly in the day before the first event).
    """
    candidates: list[FlightPick] = []
    for f in flights:
        if f.get("origin") != origin:
            continue
        if f.get("destination") != destination:
            continue
        # Date match (string compare works for ISO YYYY-MM-DD)
        if str(f.get("depart_date")) != depart_date.isoformat():
            continue
        if str(f.get("return_date")) != return_date.isoformat():
            continue

        price = float(f.get("price_usd", 0.0))
        is_provisional = bool(f.get("provisional", True))
        # Live flights get a $10,000 discount so they always beat provisional
        # at the same nominal price (and most realistic prices).
        score = price - (0.0 if is_provisional else 10_000.0)
        candidates.append(FlightPick(flight=f, score=score))

    if not candidates:
        return None
    return min(candidates, key=lambda p: p.score)


def compose_itinerary(
    candidate: IntersectionCandidate,
    events: Iterable[dict],
    flights: Iterable[dict],
    *,
    user_origin: str,
    return_window_days: int = 3,
) -> Optional[Itinerary]:
    """Build the full itinerary for one candidate.

    Steps:
      1. Resolve candidate.city → destination airport IATA.
      2. Pick the best flight: try depart = candidate.start_date - 1 day
         (so the user arrives the day before) with return = candidate.end_date
         + return_window_days. If no exact match, try other nearby dates.
      3. Organize candidate.events by start_date → DayPlan list.
      4. Estimate total cost.

    Returns None if no flight is found (no IATA match, or no flight in
    fixtures covering the route).
    """
    destination = resolve_airport(candidate.city)
    if not destination:
        return None

    flights_list = list(flights)

    # Try every (depart_offset, return_offset) pair within ±3 days
    # of the base dates, independently. This handles both "fly in early"
    # and "fly out late" without requiring a single offset to satisfy
    # both. 7×7 = 49 calls max — cheap given a few-dozen-flight catalog.
    pick: Optional[FlightPick] = None
    depart_base = candidate.start_date - timedelta(days=1)
    return_base = candidate.end_date + timedelta(days=return_window_days)
    for depart_offset in (0, -1, 1, -2, 2, -3, 3):
        if pick is not None:
            break
        d = depart_base + timedelta(days=depart_offset)
        for return_offset in (0, -1, 1, -2, 2, -3, 3):
            r = return_base + timedelta(days=return_offset)
            pick = pick_flight(
                flights_list,
                origin=user_origin,
                destination=destination,
                depart_date=d,
                return_date=r,
            )
            if pick is not None:
                break

    if pick is None:
        return None

    # Build day-by-day plan
    days_map: dict[date, DayPlan] = {}
    for matched in candidate.events:
        ev = matched.event
        ev_date = _parse_date(ev.get("start_date"))
        if ev_date is None:
            continue
        if ev_date not in days_map:
            days_map[ev_date] = DayPlan(date=ev_date, events=[], notes="")
        days_map[ev_date].events.append(ev)

    days = sorted(days_map.values(), key=lambda d: d.date)

    flight = pick.flight
    itinerary = Itinerary(
        id=candidate.id,
        candidate_id=candidate.id,
        origin=user_origin,
        destination_airport=destination,
        destination_city=candidate.city,
        destination_country=candidate.country,
        depart_date=_parse_date(flight.get("depart_date")) or candidate.start_date,
        return_date=_parse_date(flight.get("return_date")) or candidate.end_date,
        flight_price_usd=float(flight.get("price_usd", 0.0)),
        flight_booking_url=flight.get("booking_url", ""),
        flight_id=flight.get("id", ""),
        days=days,
    )
    itinerary.est_total_cost_usd = estimate_total_cost(
        itinerary.flight_price_usd,
        [e for m in candidate.events for e in [m.event]],
    )
    return itinerary


def estimate_total_cost(
    flight_price_usd: Optional[float],
    events: Iterable[dict],
) -> float:
    """Total trip cost: flight + any ticketed events.

    Events without a `ticket_price_usd` key are treated as free.
    """
    total = flight_price_usd if flight_price_usd is not None else 0.0
    for e in events:
        price = e.get("ticket_price_usd")
        if price is None:
            continue
        total += float(price)
    return total


# ─── Internals ─────────────────────────────────────────────────────────────


def _parse_date(value) -> Optional[date]:
    """Parse a date string in ISO format (YYYY-MM-DD). Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
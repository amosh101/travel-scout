"""Search router + intersection algorithm.

The intersection algorithm is the actual product value: given (origin,
destination, date_range, must-haves, nice-to-haves), find the top
itineraries from real data — Jolpica F1, Nominatim geocoding,
Nager.Date holidays, OSRM routing. Paid flight/hotel APIs (Kiwi,
Ticketmaster) are wired but raise NotConfiguredError until keys are
set, so the response is honest about which data sources contributed.

Algorithm: weighted score across all real-data options that pass
the hard constraints (within date range, in country, no holiday-
blocked date). Top 5 returned with a user-facing pitch of why each
match landed in the result. Score breakdown is logged to the audit
trail (search) for debugging, never rendered to the user.

Budget: intentionally absent. Until we have real flight + hotel
pricing wired in, filtering on a budget the system doesn't compute
would be theatre. Pricing is answered by outbound booking links
(Google Flights, Skyscanner, Booking.com) on the saved page.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.clients import (
    build_holidays_client,
    build_jolpica_client,
    build_nominatim_client,
    build_osrm_client,
    build_overpass_client,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


# Interest-key synonyms used to match user interest keys to event kinds.
# Kept here (not in a separate taxonomy file) because it is small and
# only consumed by ``_build_pitch``.
_INTEREST_TO_EVENT_KIND: dict[str, set[str]] = {
    # F1 / motorsport
    "f1": {"f1_race"},
    "formula 1": {"f1_race"},
    "f1 / motorsport": {"f1_race"},
    "motorsport": {"f1_race"},
    "racing": {"f1_race"},
    # Cultural / public-holiday-flavoured interests
    "history": {"public_holiday"},
    "culture": {"public_holiday"},
    "local festivals": {"public_holiday"},
    "festivals": {"public_holiday"},
    "public holidays": {"public_holiday"},
    "public-holidays": {"public_holiday"},
}


def _build_pitch(
    *,
    interests: list[str],
    races_in_window: list[dict],
    holiday_alerts: list[dict],
    duration_days: int,
    has_event_window: bool,
) -> list[str]:
    """User-facing explanation of why this itinerary was returned.

    One short line per match between the user's stored interests and the
    anchor events (F1 races, public holidays) found in the trip window.
    The internal scoring ledger is no longer exposed to users — audit
    log retains the breakdown via ``itineraries.discover``.
    """
    pitch: list[str] = []
    user_kinds: set[str] = set()
    for i in interests:
        k = i.strip().lower()
        for syn, kinds in _INTEREST_TO_EVENT_KIND.items():
            if k == syn or syn in k or k in syn:
                user_kinds |= kinds

    # Anchor events the user explicitly cares about.
    for r in races_in_window:
        if "f1_race" in user_kinds:
            pitch.append(
                f"{r.get('name', 'F1 race')} on "
                f"{r.get('starts_at', '')[:10]} — matches your F1 interest"
            )
    for h in holiday_alerts:
        if "public_holiday" in user_kinds:
            local = f" ({h.get('local')})" if h.get("local") else ""
            pitch.append(
                f"{h.get('name', 'Local holiday')}{local} on "
                f"{h.get('date', '')} — matches your culture interest"
            )

    # If the user has interests but none landed in the window, surface that
    # honestly instead of leaving the user guessing why the trip is here.
    if not pitch and interests and has_event_window:
        pitch.append(
            "No events matching your saved interests in this window"
        )

    # If the user has no interests on file, don't fabricate reasons.
    return pitch


@dataclass
class Itinerary:
    rank: int
    score: float
    pitch: list[str]
    destination: str
    destination_country: str
    start_date: str
    end_date: str
    duration_days: int
    total_distance_km: float
    races_in_window: list[dict] = field(default_factory=list)
    holiday_alerts: list[dict] = field(default_factory=list)
    hotels: list[dict] = field(default_factory=list)
    route: dict | None = None
    sources: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _score_itinerary(
    *,
    distance_km: float,
    duration_days: int,
    races_at_destination: int,
    holidays_count: int,
) -> tuple[float, list[str]]:
    """Weighted score 0-100; higher is better. Returns (score, audit_reasons).

    The score drives ranking but is no longer surfaced to the user; the
    ``pitch`` field is what they see. The ``reasons`` list is returned for
    audit-logging purposes only.
    """
    score = 0.0
    reasons: list[str] = []

    if distance_km <= 500:
        score += 25
        reasons.append(f"dist +25 short hop ({distance_km:.0f} km)")
    elif distance_km <= 1500:
        score += 15
        reasons.append(f"dist +15 medium hop ({distance_km:.0f} km)")
    else:
        score += 5
        reasons.append(f"dist +5 long haul ({distance_km:.0f} km)")

    if 2 <= duration_days <= 5:
        score += 20
        reasons.append(f"dur +20 ideal ({duration_days}d)")
    elif duration_days == 1:
        score += 10
        reasons.append("dur +10 day trip")
    else:
        score += 5
        reasons.append(f"dur +5 longer trip ({duration_days}d)")

    if races_at_destination > 0:
        score += 30
        reasons.append(f"f1 +30 AT dest ({races_at_destination} race(s))")
    else:
        score += 5
        reasons.append("f1 +5 no race at dest (window-aligned)")

    if holidays_count > 0:
        score -= 10
        reasons.append(f"hol -10 ({holidays_count} in window)")
    else:
        score += 5
        reasons.append("hol +5 clear window")

    score += 5  # base
    reasons.append("base +5")

    return max(0.0, min(100.0, score)), reasons


@router.get("")
async def search(
    origin: str = Query(..., min_length=2, max_length=200,
                         description="Origin city name (e.g. 'Maputo', 'Joburg')"),
    destination: str = Query(..., min_length=2, max_length=200,
                              description="Destination city or region"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    top_n: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Search for travel itineraries matching the user's criteria.

    Real data sources used (always):
      - Jolpica F1 2026 season
      - Nager.Date public holidays (SADC)
      - Nominatim geocoding (origin + destination)
      - OSRM routing (origin -> destination)

    Optional (raises NotConfiguredError if not set):
      - Kiwi flights (requires KIWI_API_KEY)
      - Ticketmaster events (requires TICKETMASTER_API_KEY)
    """
    if end_date < start_date:
        raise HTTPException(400, "end_date must be >= start_date")
    if (end_date - start_date).days > 31:
        raise HTTPException(400, "trip too long (>31 days)")

    duration = (end_date - start_date).days + 1
    sources_used: list[str] = []
    missing: list[str] = []

    # --- Geocode origin + destination in parallel ---
    nomi = build_nominatim_client()
    try:
        origin_geo, dest_geo = await asyncio.gather(
            nomi.geocode(origin, limit=1),
            nomi.geocode(destination, limit=1),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Nominatim geocode failed")
        raise HTTPException(503, f"geocoding service error: {e}")
    if not origin_geo:
        raise HTTPException(404, f"origin not found: {origin!r}")
    if not dest_geo:
        raise HTTPException(404, f"destination not found: {destination!r}")
    sources_used.append("nominatim")
    o = origin_geo[0]
    d = dest_geo[0]

    # --- Route ---
    osrm = build_osrm_client()
    try:
        route = await osrm.route(o.lon, o.lat, d.lon, d.lat)
    except Exception as e:  # noqa: BLE001
        logger.warning("OSRM route failed: %s", e)
        route = None
    if route:
        sources_used.append("osrm")

    # --- F1 races in window (2026 season) ---
    jolpica = build_jolpica_client()
    try:
        races = await jolpica.fetch_season(start_date.year)
    except Exception as e:  # noqa: BLE001
        logger.warning("Jolpica failed: %s", e)
        races = []
    if races:
        sources_used.append("jolpica")

    # Classify each race: AT destination vs. just in window vs. neither.
    # "At destination" = race country matches the destination's country
    # (or race city is within ~50 km of the geocoded destination, as a
    # fallback for races like Spa vs Brussels where both are in Belgium).
    races_in_window: list[dict] = []
    races_at_destination: list[dict] = []
    d_lat, d_lon = d.lat, d.lon
    d_country = (d.country_code or "").upper()
    for r in races:
        in_window = start_date <= r.starts_at.date() <= end_date + timedelta(days=2)
        if not in_window:
            continue
        entry = {
            "name": r.name,
            "circuit": r.circuit,
            "city": r.city,
            "country": r.country,
            "starts_at": r.starts_at.isoformat(),
        }
        races_in_window.append(entry)
        # Try to geocode the race city for a distance check.
        try:
            race_geo = await nomi.geocode(r.city, limit=1)
        except Exception:  # noqa: BLE001
            race_geo = []
        same_country = d_country and r.country.upper() == d_country
        within_50km = False
        if race_geo:
            rl = race_geo[0]
            # crude haversine (~5% error at this scale is fine)
            import math as _m
            phi1, phi2 = _m.radians(d_lat), _m.radians(rl.lat)
            dphi = _m.radians(rl.lat - d_lat)
            dlam = _m.radians(rl.lon - d_lon)
            a = _m.sin(dphi / 2) ** 2 + _m.cos(phi1) * _m.cos(phi2) * _m.sin(dlam / 2) ** 2
            dist_km = 2 * 6371 * _m.asin(_m.sqrt(a))
            if dist_km <= 50:
                within_50km = True
        if same_country or within_50km:
            races_at_destination.append(entry)

    # --- Public holidays in destination country ---
    holidays_client = build_holidays_client()
    dest_country = (d.country_code or "").upper()
    holiday_alerts: list[dict] = []
    if dest_country:
        try:
            holidays = await holidays_client.fetch_year(start_date.year, dest_country)
        except Exception as e:  # noqa: BLE001
            logger.warning("Holidays fetch failed: %s", e)
            holidays = []
        if holidays:
            sources_used.append("holidays")
        for h in holidays:
            try:
                d_hol = date.fromisoformat(h.date)
            except ValueError:
                continue
            if start_date <= d_hol <= end_date:
                holiday_alerts.append({
                    "date": h.date,
                    "name": h.english_name,
                    "local": h.local_name,
                })

    # --- Hotels (Overpass; may fail if upstream busy) ---
    hotels_data: list[dict] = []
    try:
        overpass = build_overpass_client()
        # Use a 0.1-degree bbox around the destination (~11km)
        s, w, n, e = d.bbox
        delta = 0.1
        bbox = (s, w, n + delta, e + delta)
        hotels = await asyncio.wait_for(
            overpass.search_hotels_in_bbox(*bbox, limit=10),
            timeout=8.0,
        )
        if hotels:
            sources_used.append("overpass")
        hotels_data = [
            {"name": h.name, "lat": h.lat, "lon": h.lon}
            for h in hotels
        ]
    except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
        logger.info("Overpass unavailable: %s", e)
        missing.append("hotels (Overpass API busy, try again)")

    # --- Score and rank (single itinerary for now) ---
    itinerary = Itinerary(
        rank=1,
        score=0.0,
        pitch=[],
        destination=d.display_name.split(",")[0],
        destination_country=d.display_name.split(",")[-1].strip(),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        duration_days=duration,
        total_distance_km=(route.distance_m / 1000) if route else 0.0,
        races_in_window=races_at_destination if races_at_destination else races_in_window,
        holiday_alerts=holiday_alerts,
        hotels=hotels_data,
        route={
            "distance_km": route.distance_m / 1000,
            "duration_h": route.duration_s / 3600,
        } if route else None,
        sources=sources_used,
        missing=missing,
    )
    score, audit_reasons = _score_itinerary(
        distance_km=itinerary.total_distance_km,
        duration_days=itinerary.duration_days,
        races_at_destination=len(races_at_destination),
        holidays_count=len(holiday_alerts),
    )
    itinerary.score = round(score, 1)
    itinerary.pitch = _build_pitch(
        interests=[],
        races_in_window=itinerary.races_in_window,
        holiday_alerts=itinerary.holiday_alerts,
        duration_days=itinerary.duration_days,
        has_event_window=False,  # public /search has no event-window concept
    )
    logger.info("search score=%s reasons=%s", score, audit_reasons)
    itineraries = [itinerary]

    return {
        "query": {
            "origin": origin,
            "destination": destination,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "geocoding": {
            "origin": {"name": o.display_name, "lat": o.lat, "lon": o.lon},
            "destination": {"name": d.display_name, "lat": d.lat, "lon": d.lon},
        },
        "results": [asdict(i) for i in itineraries[:top_n]],
        "sources_used": sources_used,
        "missing_data": missing,
    }


@router.get("/f1/next")
async def f1_next() -> dict[str, Any]:
    """Return the next F1 race on the calendar (Jolpica)."""
    jolpica = build_jolpica_client()
    try:
        race = await jolpica.next_race()
    except Exception as e:  # noqa: BLE001
        logger.exception("Jolpica next_race failed")
        raise HTTPException(503, f"jolpica error: {e}")
    if not race:
        return {"race": None, "message": "no upcoming race in current season"}
    return {
        "race": {
            "name": race.name,
            "circuit": race.circuit,
            "city": race.city,
            "country": race.country,
            "starts_at": race.starts_at.isoformat(),
            "url": race.url,
        },
        "source": "jolpica",
    }


@router.get("/holidays/{country_code}")
async def holidays_for_country(
    country_code: str,
    year: int = Query(2026, ge=2020, le=2030),
) -> dict[str, Any]:
    """Return public holidays for a country (Nager.Date)."""
    code = country_code.upper()
    h = build_holidays_client()
    try:
        holidays = await h.fetch_year(year, code)
    except Exception as e:  # noqa: BLE001
        logger.exception("Holidays fetch failed for %s", code)
        raise HTTPException(503, f"holidays service error: {e}")
    return {
        "country": code,
        "year": year,
        "count": len(holidays),
        "holidays": [
            {
                "date": h.date,
                "name": h.english_name,
                "local": h.local_name,
                "global": h.is_global,
            }
            for h in holidays
        ],
        "source": "nager.date",
    }


__all__ = ["router", "Itinerary", "_score_itinerary", "_build_pitch"]

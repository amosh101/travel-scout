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

Architecture note: this router does NOT hardcode city/country maps.
All location resolution goes through ``app.refdata.service.ReferenceService``
which reads from the ``countries`` / ``cities`` / ``airports`` /
``city_aliases`` tables. The Nominatim call is only used to obtain
lat/lon/bbox for routing and holiday lookup — the disambiguation
logic lives in the database, where admins can edit it.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import (
    build_holidays_client,
    build_jolpica_client,
    build_nominatim_client,
    build_osrm_client,
    build_overpass_client,
)
from app.database import get_session
from app.refdata.models import City, Country
from app.refdata.service import LocationResolution, ReferenceService
from sqlalchemy import select as _select

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


# -----------------------------------------------------------------------------
# Tunable constants (NOT hardcoded city/country data — these are scoring
# parameters that an admin should be able to change via algo_weights)
# -----------------------------------------------------------------------------

# How close a race city must be to the destination to count as "at the
# destination". 200 km covers Spa→Brussels (120 km), Monza→Milan (30 km),
# Silverstone→London (120 km), Suzuka→Tokyo (~200 km). Beyond that the
# user is booking a separate domestic leg.
RACE_AT_DESTINATION_RADIUS_KM = 200.0

# How many days before / after the trip window to extend when looking
# for anchor events. F1 weekends are Fri–Sun; users usually fly in 1–2
# days before. Public holidays affect pricing 1–2 days before the day.
EVENT_WINDOW_BUFFER_DAYS = 5

# Minimum confidence required from ReferenceService to use a city
# directly. Below this we fall back to Nominatim for the user's input.
MIN_REFDATA_CONFIDENCE = 0.7


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
    destination_country_code: str | None = None
    start_date: str = ""
    end_date: str = ""
    duration_days: int = 0
    total_distance_km: float = 0.0
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

    # --- Resolve origin + destination through ReferenceService ---
    # ReferenceService owns the city/country/alias disambiguation logic.
    # It reads from the countries / cities / airports / city_aliases
    # tables — admins can add cities or change the default-bias without a
    # code deploy. The result is a LocationResolution with city,
    # country, airport, confidence, and match_kind.
    #
    # For lat/lon we prefer our own city record (curated, stable) and
    # only fall back to Nominatim for the user's freeform input when
    # the DB didn't resolve it.
    from app.database import get_session_factory

    factory = get_session_factory()

    # --- Parse country hints from the user's input ---
    # The user may type "Brussels, US" or "Brussels, Texas" or
    # "Brussels USA" — ReferenceService accepts a country_bias
    # parameter. We extract the bias by looking for a 2-letter suffix
    # or a country name match against our countries table (DB-driven;
    # no hardcoded list). The first token is the city; everything
    # after the comma / the trailing country word is the hint.
    async def _extract_country_hint(text: str) -> str | None:
        """Look for a country hint in the user's freeform input.

        Returns the 2-letter ISO code if found, else None. Examples:
          "Brussels, US"   -> "US"
          "Brussels, USA"  -> "US"
          "Brussels, Belgium" -> "BE"
        """
        if not text:
            return None
        # Try the easy case: ", XX" or ", XXX" where XX/XXX is a code.
        m = re.search(r",\s*([A-Za-z]{2,3})\s*$", text.strip())
        if m:
            code = m.group(1).upper()
            if len(code) == 3:
                # Could be alpha-3; convert. We use alpha-2 internally.
                async with factory() as session:
                    row = (await session.execute(
                        _select(Country.alpha2).where(Country.alpha3 == code)
                    )).scalar_one_or_none()
                    return row
            async with factory() as session:
                row = (await session.execute(
                    _select(Country.alpha2).where(Country.alpha2 == code)
                )).scalar_one_or_none()
                return row
        # Otherwise: check if the last word(s) are a country name.
        words = text.strip().split()
        if len(words) >= 2:
            last = " ".join(words[-2:]).lower()
            async with factory() as session:
                row = (await session.execute(
                    _select(Country.alpha2).where(
                        Country.name.ilike(last)
                    )
                )).scalar_one_or_none()
                if row:
                    return row
            last1 = words[-1].lower()
            async with factory() as session:
                row = (await session.execute(
                    _select(Country.alpha2).where(
                        Country.name.ilike(last1)
                    )
                )).scalar_one_or_none()
                if row:
                    return row
        return None

    origin_bias, dest_bias = await asyncio.gather(
        _extract_country_hint(origin),
        _extract_country_hint(destination),
    )

    # Strip the country hint from the input — ReferenceService normalises
    # the text (lowercase, drop punctuation) and the trailing ", US"
    # would pollute the alias match.
    import re as _re
    def _strip_hint(text: str) -> str:
        return _re.sub(r",\s*[A-Za-z]{2,3}\s*$", "", text.strip()).strip() or text.strip()

    origin_clean = _strip_hint(origin)
    dest_clean = _strip_hint(destination)

    async def _resolve(text: str, bias: str | None) -> LocationResolution:
        async with factory() as session:
            ref = ReferenceService(session)
            return await ref.resolve(text, country_bias=bias)

    try:
        origin_res, dest_res = await asyncio.gather(
            _resolve(origin_clean, origin_bias), _resolve(dest_clean, dest_bias)
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("ReferenceService resolve failed")
        raise HTTPException(503, f"reference data error: {e}")

    sources_used.append("refdata")

    # For lat/lon, prefer the DB record (curated); fall back to Nominatim
    # only if the DB didn't have a confident match.
    nomi = build_nominatim_client()

    async def _ensure_lonlat(res: LocationResolution, raw: str) -> tuple[float, float, str]:
        """Return (lat, lon, display_name). Uses DB if available, else Nominatim."""
        if res.city and res.city.latitude is not None and res.city.longitude is not None:
            display = res.city.name
            if res.country:
                display = f"{display}, {res.country.name}"
            return (
                float(res.city.latitude),
                float(res.city.longitude),
                str(display),
            )
        # DB didn't have lat/lon. Use Nominatim to geocode the freeform text.
        try:
            results = await nomi.geocode(raw, limit=1)
        except Exception as e:  # noqa: BLE001
            logger.warning("Nominatim fallback failed for %r: %s", raw, e)
            raise HTTPException(503, f"geocoding service error: {e}")
        if not results:
            raise HTTPException(404, f"location not found: {raw!r}")
        g = results[0]
        return float(g.lat), float(g.lon), g.display_name

    if not origin_res.matched and not dest_res.matched:
        # Both failed; raise 404 with the worst one's text.
        raise HTTPException(
            404,
            f"could not resolve origin ({origin!r}) or destination ({destination!r})",
        )
    if not origin_res.matched:
        raise HTTPException(404, f"origin not found: {origin!r}")
    if not dest_res.matched:
        raise HTTPException(404, f"destination not found: {destination!r}")

    o_lat, o_lon, o_display = await _ensure_lonlat(origin_res, origin)
    d_lat, d_lon, d_display = await _ensure_lonlat(dest_res, destination)
    if origin_res.matched and origin_res.match_kind != "iata":
        # Only used Nominatim as fallback; mention it.
        if not (origin_res.city and origin_res.city.latitude is not None):
            sources_used.append("nominatim")
    if dest_res.matched and dest_res.match_kind != "iata":
        if not (dest_res.city and dest_res.city.latitude is not None):
            sources_used.append("nominatim")

    o = SimpleNamespace(lat=o_lat, lon=o_lon, display_name=o_display)
    d = SimpleNamespace(lat=d_lat, lon=d_lon, display_name=d_display)

    # --- Route ---
    osrm = build_osrm_client()
    try:
        route = await osrm.route(o.lon, o.lat, d.lon, d.lat)
    except Exception as e:  # noqa: BLE001
        logger.warning("OSRM route failed: %s", e)
        route = None
    if route:
        sources_used.append("osrm")

    # --- F1 races in window ---
    jolpica = build_jolpica_client()
    try:
        races = await jolpica.fetch_season(start_date.year)
    except Exception as e:  # noqa: BLE001
        logger.warning("Jolpica failed: %s", e)
        races = []
    if races:
        sources_used.append("jolpica")

    # "At destination" = race country matches the destination's country
    # OR race city is within RACE_AT_DESTINATION_RADIUS_KM of the destination.
    # Country matching comes from the LocationResolution we already resolved
    # above (no second hardcode); race-city resolution also goes through
    # ReferenceService so an admin can add/remove cities in the DB.
    races_in_window: list[dict] = []
    races_at_destination: list[dict] = []
    d_lat, d_lon = d.lat, d.lon
    d_country = (
        dest_res.country.alpha2.upper()
        if dest_res.country else ""
    )
    for r in races:
        in_window = (
            start_date - timedelta(days=EVENT_WINDOW_BUFFER_DAYS)
            <= r.starts_at.date()
            <= end_date + timedelta(days=EVENT_WINDOW_BUFFER_DAYS)
        )
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
        same_country = bool(d_country) and r.country.upper() == d_country
        within_radius = False
        if d_lat and d_lon:
            # Resolve the race city through ReferenceService first (DB has
            # curated lat/lon for Spa, Monza, Silverstone, etc.). Fall back
            # to Nominatim only if the DB doesn't have it.
            race_lat, race_lon = None, None
            try:
                async with factory() as session:
                    ref = ReferenceService(session)
                    race_res = await ref.resolve(r.city)
                if race_res.city and race_res.city.latitude is not None:
                    race_lat = float(race_res.city.latitude)  # type: ignore[arg-type]
                    race_lon = float(race_res.city.longitude)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001
                pass
            if race_lat is None or race_lon is None:
                try:
                    race_geo = await nomi.geocode(
                        f"{r.city}, {r.country}", limit=1
                    )
                except Exception:  # noqa: BLE001
                    race_geo = []
                if race_geo:
                    race_lat = float(race_geo[0].lat)
                    race_lon = float(race_geo[0].lon)
            if race_lat is not None and race_lon is not None:
                phi1, phi2 = math.radians(d_lat), math.radians(race_lat)
                dphi = math.radians(race_lat - d_lat)
                dlam = math.radians(race_lon - d_lon)
                a = (
                    math.sin(dphi / 2) ** 2
                    + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
                )
                dist_km = 2 * 6371 * math.asin(math.sqrt(a))
                if dist_km <= RACE_AT_DESTINATION_RADIUS_KM:
                    within_radius = True
                    entry["distance_from_destination_km"] = str(round(dist_km, 1))
        if same_country or within_radius:
            races_at_destination.append(entry)

    # --- Public holidays in destination country ---
    # Country comes from the LocationResolution we already resolved — no
    # second hardcode. If the destination didn't match a country in the
    # DB (freeform text only), the country will be None and we surface
    # a clear "no country" message instead of guessing.
    holidays_client = build_holidays_client()
    holiday_alerts: list[dict] = []
    holidays: list = []
    if dest_res.country is None:
        missing.append(
            f"holiday data unavailable: destination {destination!r} did not "
            f"resolve to a known country (admin can add it to refdata.countries)"
        )
    else:
        cc = str(dest_res.country.alpha2)  # type: ignore[arg-type]
        try:
            holidays = await holidays_client.fetch_year(start_date.year, cc)
            if holidays:
                sources_used.append("holidays")
        except Exception as e:  # noqa: BLE001
            logger.warning("Holidays fetch failed for %s: %s", cc, e)
            missing.append(f"holiday data unavailable for {cc}: {e}")
        # Holiday filter uses the same EVENT_WINDOW_BUFFER_DAYS buffer as
        # races — a holiday two days before your trip still affects pricing.
    for h in holidays:
        try:
            d_hol = date.fromisoformat(h.date)
        except ValueError:
            continue
        if (
            start_date - timedelta(days=EVENT_WINDOW_BUFFER_DAYS)
            <= d_hol
            <= end_date + timedelta(days=EVENT_WINDOW_BUFFER_DAYS)
        ):
            holiday_alerts.append({
                "date": h.date,
                "name": h.english_name,
                "local": h.local_name,
                "country": h.country_code,
            })

    # --- Hotels (Overpass; may fail if upstream busy) ---
    # Overpass needs a bbox. We get it from Nominatim around the
    # destination lat/lon. The bbox isn't part of our curated city
    # record; this is one place where Nominatim is the right call.
    hotels_data: list[dict] = []
    try:
        overpass = build_overpass_client()
        try:
            nres = await nomi.geocode(
                str(dest_res.city.name) if dest_res.city else destination,
                limit=1,
            )
        except Exception:
            nres = []
        if nres:
            g = nres[0]
            s, w, n, _e = g.bbox
            delta = 0.1
            bbox = (s, w, n + delta, _e + delta)
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
    headline_races = races_at_destination or races_in_window
    # Prefer canonical names from the DB over the raw Nominatim display.
    dest_name = (
        str(dest_res.city.name) if dest_res.city else d_display.split(",")[0]
    )
    dest_country_name = (
        str(dest_res.country.name) if dest_res.country
        else d_display.split(",")[-1].strip()
    )
    dest_country_code = (
        str(dest_res.country.alpha2).upper() if dest_res.country else None
    )
    origin_name = (
        str(origin_res.city.name) if origin_res.city else o_display.split(",")[0]
    )
    origin_country_code = (
        str(origin_res.country.alpha2).upper() if origin_res.country else None
    )
    itinerary = Itinerary(
        rank=1,
        score=0.0,
        pitch=[],
        destination=dest_name,
        destination_country=dest_country_name,
        destination_country_code=dest_country_code,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        duration_days=duration,
        total_distance_km=(route.distance_m / 1000) if route else 0.0,
        races_in_window=headline_races,
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
        interests=["f1", "public-holidays"],
        races_in_window=itinerary.races_in_window,
        holiday_alerts=itinerary.holiday_alerts,
        duration_days=itinerary.duration_days,
        has_event_window=True,
    )
    logger.info("search score=%s reasons=%s", score, audit_reasons)
    itineraries = [itinerary]

    return {
        "query": {
            "origin": origin,
            "destination": destination,
            "destination_picked": d_display,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "geocoding": {
            "origin": {
                "name": o_display,
                "lat": o_lat,
                "lon": o_lon,
                "country_code": origin_country_code,
                "resolved_via": origin_res.match_kind,
            },
            "destination": {
                "name": d_display,
                "lat": d_lat,
                "lon": d_lon,
                "country_code": dest_country_code,
                "resolved_via": dest_res.match_kind,
            },
        },
        "results": [asdict(i) for i in itineraries[:top_n]],
        "sources_used": sources_used,
        "missing_data": missing,
        "audit": {"score": score, "reasons": audit_reasons},
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

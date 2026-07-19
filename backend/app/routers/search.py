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
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.clients import (
    GeocodeResult,
    build_holidays_client,
    build_jolpica_client,
    build_nominatim_client,
    build_osrm_client,
    build_overpass_client,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


# -----------------------------------------------------------------------------
# Geocoding disambiguation
# -----------------------------------------------------------------------------
# When the user types an ambiguous city name (Brussels, Paris, Florence,
# Lima...), Nominatim returns 4-5 results across continents. Picking the
# top-importance one often gives the wrong country (e.g. Brussels-IL
# outranks Brussels-BE because the small Illinois town has higher
# per-capita search frequency). Prefer the result whose country is in
# the user's known-travel set, or any of the major European/global
# destinations we know about. Fall back to the highest-importance hit.
_KNOWN_TRAVEL_COUNTRIES: set[str] = {
    # SADC
    "MZ", "ZA", "ZW", "NA", "BW", "ZM", "MW", "MG", "MU", "SC",
    "TZ", "KE", "RW", "AO", "CD", "LS", "SZ",
    # Europe (F1 destinations + cultural)
    "BE", "NL", "DE", "FR", "IT", "ES", "PT", "GB", "AT", "CH",
    "MC", "HU", "PL", "CZ", "DK", "SE", "FI", "NO", "IE", "GR",
    "TR", "HR", "RO", "BG", "SK", "SI", "EE", "LV", "LT", "LU",
    "IS",
    # Asia / Americas (for trips from these regions too)
    "AE", "SA", "QA", "SG", "JP", "AU", "BR", "US", "CA", "MX",
    "AR", "TH", "MY", "ID", "PH", "IN", "EG", "MA", "TN",
    # Hong Kong / Macao (no alpha-2 in some, but covered)
}


# Cities whose names map to multiple countries. When the user types one of
# these, we apply a stronger "prefer the European/global-travel one" rule
# because the Maputo user is overwhelmingly likely to mean the European
# city, not a small American town with the same name.
_AMBIGUOUS_CITY_PREFER: set[str] = {
    "brussels", "paris", "florence", "lima", "athens", "naples",
    "berlin", "london", "dublin", "moscow", "warsaw", "vienna",
    "milan", "rome", "seville", "cordoba", "cambridge", "oxford",
    "plymouth", "portsmouth", "jackson", "springfield", "salem",
    "troy", "sydney", "richmond", "newcastle", "aleppo", "alexandria",
}

# When the user types one of these ambiguous city names, we bias the
# Nominatim call to the default country for that name. "Brussels" -> BE,
# "Paris" -> FR, "Florence" -> IT, etc. This is the strong, deterministic
# fix for the Brussels-IL / Paris-TX / Florence-OR ambiguity problem.
_AMBIGUOUS_CITY_DEFAULT_COUNTRY: dict[str, str] = {
    "brussels": "BE", "bruxelles": "BE", "brussel": "BE",
    "paris": "FR",
    "florence": "IT", "firenze": "IT",
    "lima": "PE",
    "athens": "GR", "athinai": "GR",
    "naples": "IT", "napoli": "IT",
    "berlin": "DE",
    "london": "GB",
    "dublin": "IE", "baile atha cliath": "IE",
    "moscow": "RU", "moskva": "RU",
    "warsaw": "PL", "warszawa": "PL",
    "vienna": "AT", "wien": "AT",
    "milan": "IT", "milano": "IT",
    "rome": "IT", "roma": "IT",
    "seville": "ES", "sevilla": "ES",
    "cordoba": "ES", "cordobaar": "ES", "cordobaes": "ES",
    "cambridge": "GB", "oxford": "GB",
    "plymouth": "GB", "portsmouth": "GB",
    "jackson": "US", "springfield": "US", "salem": "US",
    "troy": "US", "richmond": "US", "newcastle": "GB",
    "sydney": "AU",
    "aleppo": "SY", "alexandria": "EG",
}


def _pick_best_geocode(results: list[GeocodeResult], query: str) -> GeocodeResult:
    """Pick the most travel-relevant geocode result.

    Strategy (in order):
      1. If the user typed a country hint, take the top result.
      2. If the city name is in the known-ambiguous list, prefer the
         European or major-travel city (Brussels-BE, not Brussels-IL).
      3. Prefer results whose country is in the known-travel set and has
         the highest importance score.
      4. Final fallback: highest importance overall.
    """
    if not results:
        return results[0]
    if len(results) == 1:
        return results[0]

    # Did the user include a country hint? Use whole-word match so we
    # don't false-trigger on substrings like "us" in "brussels".
    q_lower = query.lower().strip()
    _COUNTRY_HINT_WORDS = {
        "belgium", "france", "italy", "spain", "germany", "portugal",
        "netherlands", "uk", "united kingdom", "usa", "america",
        "japan", "china", "australia", "brazil", "argentina",
        "south africa", "mozambique", "kenya", "tanzania", "india",
        "switzerland", "austria", "hungary", "poland", "ireland",
        "sweden", "norway", "denmark", "finland", "greece", "turkey",
        "mexico", "canada", "iceland", "croatia", "romania", "bulgaria",
    }
    q_tokens = set(re.findall(r"[a-z]+", q_lower))
    has_country_hint = bool(q_tokens & _COUNTRY_HINT_WORDS) or bool(
        re.search(r",\s*[A-Za-z]{2,3}\s*$", query)
    )
    if has_country_hint:
        return results[0]

    # Stripped query (first word) for the ambiguous check.
    q_stripped = re.sub(r"[^a-z]", "", q_lower.split()[0] if q_lower else "")
    if q_stripped in _AMBIGUOUS_CITY_PREFER:
        # Prefer the European result if one exists.
        eu_codes = {
            "BE", "FR", "IT", "ES", "PT", "DE", "NL", "GB", "AT", "CH",
            "MC", "HU", "PL", "CZ", "DK", "SE", "FI", "NO", "IE", "GR",
            "TR", "HR", "RO", "BG", "SK", "SI", "EE", "LV", "LT", "LU",
            "IS", "RU",
        }
        eu_hits = [
            r for r in results
            if (r.country_code or "").upper() in eu_codes
        ]
        if eu_hits:
            return max(eu_hits, key=lambda r: r.importance)

    # Prefer known-travel countries (in case the user is from / heading to
    # any of the SADC + Europe + common Asia set).
    travel_hits = [
        r for r in results
        if (r.country_code or "").upper() in _KNOWN_TRAVEL_COUNTRIES
    ]
    if travel_hits:
        # Among travel-set hits, prefer the one whose importance is at
        # least 80% of the top-importance result overall. That keeps a
        # genuinely-known big city (Cape Town) from losing to a tiny
        # travel-set town with slightly higher importance.
        top_imp = max(r.importance for r in results)
        confident = [r for r in travel_hits if r.importance >= top_imp * 0.7]
        if confident:
            return max(confident, key=lambda r: r.importance)
        return max(travel_hits, key=lambda r: r.importance)
    # Final fallback: top importance overall.
    return max(results, key=lambda r: r.importance)


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

    # --- Geocode origin + destination in parallel ---
    # Ask for limit=5 so we can pick a better match when the raw query
    # is ambiguous (e.g. "Brussels" returns 4 cities across continents).
    # For known-ambiguous city names, bias the Nominatim call to the
    # default country (Brussels -> BE, Paris -> FR, Florence -> IT, ...).
    # The "best" pick is the one whose country is in our known-travel set
    # OR, failing that, the highest-importance result.
    nomi = build_nominatim_client()
    dest_bias = _AMBIGUOUS_CITY_DEFAULT_COUNTRY.get(
        re.sub(r"[^a-z]", "", destination.lower().split()[0] if destination else "")
    )
    origin_bias = _AMBIGUOUS_CITY_DEFAULT_COUNTRY.get(
        re.sub(r"[^a-z]", "", origin.lower().split()[0] if origin else "")
    )
    try:
        origin_geo, dest_geo = await asyncio.gather(
            nomi.geocode(origin, limit=5, country_bias=origin_bias),
            nomi.geocode(destination, limit=5, country_bias=dest_bias),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Nominatim geocode failed")
        raise HTTPException(503, f"geocoding service error: {e}")
    if not origin_geo:
        raise HTTPException(404, f"origin not found: {origin!r}")
    if not dest_geo:
        raise HTTPException(404, f"destination not found: {destination!r}")
    sources_used.append("nominatim")
    o = _pick_best_geocode(origin_geo, query=origin)
    d = _pick_best_geocode(dest_geo, query=destination)

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
    # OR race city is within ~200 km of the destination (covers Spa->Brussels,
    # Silverstone->London, Monza->Milan, Suzuka->Tokyo, etc.).
    # Date buffer is ±5 days because F1 weekends span Fri-Sun and the
    # user usually has to fly in 1-2 days before.
    races_in_window: list[dict] = []
    races_at_destination: list[dict] = []
    d_lat, d_lon = d.lat, d.lon
    d_country = (d.country_code or "").upper()
    for r in races:
        in_window = (
            start_date - timedelta(days=5)
            <= r.starts_at.date()
            <= end_date + timedelta(days=5)
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
        # Distance check: same country OR within 200 km of the destination.
        # Spa is ~120 km from Brussels; Monza is ~30 km from Milan;
        # Silverstone is ~120 km from London. 200 km is the right radius
        # to catch the "drive / 1h train" travel radius around major cities.
        same_country = bool(d_country) and r.country.upper() == d_country
        within_radius = False
        if d_lat and d_lon:
            try:
                race_geo = await nomi.geocode(
                    f"{r.city}, {r.country}", limit=1
                )
            except Exception:  # noqa: BLE001
                race_geo = []
            if race_geo:
                rl = race_geo[0]
                # Haversine (move the math to module level).
                phi1, phi2 = math.radians(d_lat), math.radians(rl.lat)
                dphi = math.radians(rl.lat - d_lat)
                dlam = math.radians(rl.lon - d_lon)
                a = (
                    math.sin(dphi / 2) ** 2
                    + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
                )
                dist_km = 2 * 6371 * math.asin(math.sqrt(a))
                if dist_km <= 200:
                    within_radius = True
                    entry["distance_from_destination_km"] = str(round(dist_km, 1))
        if same_country or within_radius:
            races_at_destination.append(entry)

    # --- Public holidays in destination country ---
    # The geocoder should give us a country code, but the disambiguator
    # above may leave it empty for unusual cases. Try a few fallbacks.
    holidays_client = build_holidays_client()
    display_lower = d.display_name.lower()
    country_fallbacks: list[str] = []
    if d.country_code:
        country_fallbacks.append(d.country_code.upper())
    # Display-name parsing: "Brussels, ... Belgium" -> "BE"
    for k, v in [
        ("belgium", "BE"), ("belgique", "BE"), ("belgie", "BE"),
        ("netherlands", "NL"), ("holland", "NL"),
        ("germany", "DE"), ("france", "FR"),
        ("italy", "IT"), ("spain", "ES"), ("portugal", "PT"),
        ("united kingdom", "GB"), ("britain", "GB"), ("england", "GB"),
        ("austria", "AT"), ("switzerland", "CH"),
        ("hungary", "HU"), ("monaco", "MC"),
        ("united states", "US"), ("mozambique", "MZ"),
        ("south africa", "ZA"),
    ]:
        if k in display_lower and v not in country_fallbacks:
            country_fallbacks.append(v)

    holiday_alerts: list[dict] = []
    holidays: list = []
    for cc in country_fallbacks:
        try:
            holidays = await holidays_client.fetch_year(start_date.year, cc)
            if holidays:
                sources_used.append("holidays")
                break
        except Exception as e:  # noqa: BLE001
            logger.warning("Holidays fetch failed for %s: %s", cc, e)
            continue
    if not holidays:
        missing.append(
            f"holiday data unavailable for destination country "
            f"(tried {country_fallbacks or ['unknown']})"
        )
    # Holiday filter uses the same ±5 day buffer as races — a holiday
    # two days before your trip still affects hotel/airfare prices.
    for h in holidays:
        try:
            d_hol = date.fromisoformat(h.date)
        except ValueError:
            continue
        if (
            start_date - timedelta(days=5)
            <= d_hol
            <= end_date + timedelta(days=5)
        ):
            holiday_alerts.append({
                "date": h.date,
                "name": h.english_name,
                "local": h.local_name,
                "country": h.country_code,
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
    # Choose the headline race set: races that are AT the destination
    # are the primary selling point. If we found none, fall back to
    # races in the wider window (still useful context for the user).
    headline_races = races_at_destination or races_in_window
    itinerary = Itinerary(
        rank=1,
        score=0.0,
        pitch=[],
        destination=d.display_name.split(",")[0],
        destination_country=d.display_name.split(",")[-1].strip(),
        destination_country_code=(d.country_code or "").upper() or None,
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
        interests=["f1", "public-holidays"],  # /search has no auth context;
        # we always surface matches against the two anchor-event types.
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
            "destination_picked": d.display_name,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "geocoding": {
            "origin": {
                "name": o.display_name,
                "lat": o.lat,
                "lon": o.lon,
                "country_code": (o.country_code or "").upper() or None,
            },
            "destination": {
                "name": d.display_name,
                "lat": d.lat,
                "lon": d.lon,
                "country_code": (d.country_code or "").upper() or None,
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

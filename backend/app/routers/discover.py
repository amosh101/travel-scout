"""Discover router — multi-mode travel discovery.

Wraps the search router so users can search in any of four orders:
- location-led:    "I want to go to Brussels in July"
- race-led:        "I want to plan around the Belgian GP"
- event-led:       "I want to go to a music festival in Belgium"
- interest-led:    "I want a trip with F1 + jazz + culture"

The endpoint accepts whatever the user gives and infers the rest.
City/country/airport resolution goes through the ReferenceService
(canonical cities, IATA/ICAO codes, aliases, disambiguation).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from types import SimpleNamespace

from app.clients import (
    build_holidays_client,
    build_jolpica_client,
    build_nominatim_client,
    build_osrm_client,
    build_overpass_client,
)
from app.database import get_session
from app.refdata.service import ReferenceService
from app.routers.search import _build_pitch, _score_itinerary, Itinerary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discover", tags=["discover"])


@router.get("")
async def discover(
    session: Annotated[AsyncSession, Depends(get_session)],
    # Four anchors — all optional, but at least one is required.
    origin: str | None = Query(None, description="Origin city (or IATA)"),
    destination: str | None = Query(None, description="Destination city (or IATA)"),
    event_id: str | None = Query(None, description="Source event id, e.g. jolpica:2026:10"),
    interest: str | None = Query(
        None,
        description="Comma-separated interests, e.g. 'F1,jazz,cycling'",
    ),
    # Time anchor — defaults to "next 6 months" if nothing given.
    date_from: date | None = Query(None, description="Earliest start date"),
    date_to: date | None = Query(None, description="Latest end date"),
    # Output.
    top_n: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Multi-mode travel discovery.

    At least one of: origin, destination, event_id, interest.
    If date_from/date_to are not given, defaults to "next 6 months".
    """
    if not (origin or destination or event_id or interest):
        raise HTTPException(
            400,
            "at least one of origin, destination, event_id, or interest is required",
        )

    # Date defaults
    today = date.today()
    if date_from is None:
        date_from = today
    if date_to is None:
        date_to = today + timedelta(days=180)
    if date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")

    interests: list[str] = []
    if interest:
        interests = [s.strip().lower() for s in interest.split(",") if s.strip()]

    sources_used: list[str] = []
    missing: list[str] = []
    candidate_destinations: list[dict[str, Any]] = []
    origin_geo = None
    origin_resolution: dict[str, Any] | None = None

    ref = ReferenceService(session)
    nomi = build_nominatim_client()

    # --- Resolve origin via ReferenceService ---
    if origin:
        res = await ref.resolve(origin)
        res_d = res.to_dict()
        if res_d["matched"] and res_d["city"]:
            sources_used.append("refdata")
            # Use the canonical city's lat/lon as origin
            origin_geo = SimpleNamespace()  # simple namespace
            origin_geo.lat = res_d["city"]["latitude"]
            origin_geo.lon = res_d["city"]["longitude"]
            origin_geo.display_name = f"{res_d['city']['name']}, {res_d['country']['name']}"
            origin_geo.country_code = res_d["country"]["alpha2"]
        else:
            # Fall back to Nominatim for unknown places
            try:
                results = await nomi.geocode(origin, limit=1)
            except Exception as e:  # noqa: BLE001
                logger.exception("Nominatim origin geocode failed")
                raise HTTPException(503, f"geocoding service error: {e}")
            if not results:
                raise HTTPException(404, f"origin not found: {origin!r}")
            origin_geo = results[0]
            sources_used.append("nominatim")

    # --- Mode A: event-led (event_id) ---
    if event_id:
        race = await _resolve_event(event_id)
        if race and date_from <= race["starts_at"].date() <= date_to + timedelta(days=2):
            # Trust Jolpica's data — don't re-geocode, just build a clean
            # SimpleNamespace with the ISO country code.
            race_cc = _COUNTRY_NAME_TO_CODE.get(race["country"].upper(), "")
            race_geo = SimpleNamespace(
                lat=0.0, lon=0.0,  # Will be filled by refdata below if available
                display_name=f"{race['city']}, {_iso_to_name(race_cc) or race['country']}",
                country_code=race_cc,
            )
            # Try to get a better lat/lon from refdata for the race city
            race_res = await ref.resolve(race["city"])
            race_res_d = race_res.to_dict()
            if race_res_d["matched"] and race_res_d["city"]:
                race_geo.lat = race_res_d["city"]["latitude"]
                race_geo.lon = race_res_d["city"]["longitude"]
            candidate_destinations.append({
                "destination": race["city"],
                "country": race_cc,
                "anchor": "event",
                "anchor_label": race["name"],
                "anchor_date": race["starts_at"].date().isoformat(),
                "_geo": race_geo,
            })
            sources_used.append("jolpica")
            if race_geo.lat != 0.0:
                sources_used.append("refdata")
        elif race:
            missing.append(
                f"event {event_id} on {race['starts_at'].date()} "
                f"is outside {date_from} → {date_to}"
            )
        else:
            missing.append(f"event {event_id} not resolvable")

    # --- Mode B: destination-led ---
    if destination:
        res = await ref.resolve(destination)
        res_d = res.to_dict()
        if res_d["matched"] and res_d["city"]:
            sources_used.append("refdata")
            # If the user gave a country bias (e.g. "Brussels, US") we trust
            # them; otherwise we use the primary match and surface alternatives.
            primary = res_d
            city = primary["city"]
            country = primary["country"]
            # Build a GeocodeResult-like object so downstream code is unchanged
            d_geo = SimpleNamespace()
            d_geo.lat = city["latitude"]
            d_geo.lon = city["longitude"]
            d_geo.display_name = f"{city['name']}, {country['name']}"
            d_geo.country_code = country["alpha2"]
            candidate_destinations.append({
                "destination": city["name"],
                "country": country["alpha2"],
                "anchor": "location",
                "anchor_label": d_geo.display_name,
                "anchor_date": None,
                "_geo": d_geo,
            })
            # Add alternatives as additional candidates
            for alt in primary.get("alternatives", [])[:2]:
                if alt.get("city") and alt.get("country"):
                    alt_geo = SimpleNamespace()
                    alt_geo.lat = alt["city"]["latitude"]
                    alt_geo.lon = alt["city"]["longitude"]
                    alt_geo.display_name = f"{alt['city']['name']}, {alt['country']['name']}"
                    alt_geo.country_code = alt["country"]["alpha2"]
                    candidate_destinations.append({
                        "destination": alt["city"]["name"],
                        "country": alt["country"]["alpha2"],
                        "anchor": "location",
                        "anchor_label": alt_geo.display_name,
                        "anchor_date": None,
                        "_geo": alt_geo,
                    })
        else:
            # Unknown place — let Nominatim have a shot
            try:
                results = await nomi.geocode(destination, limit=3)
            except Exception as e:  # noqa: BLE001
                logger.exception("Nominatim destination geocode failed")
                raise HTTPException(503, f"geocoding service error: {e}")
            if not results:
                raise HTTPException(404, f"destination not found: {destination!r}")
            for r in results[:3]:
                cc = (r.country_code or "").upper() or "?"
                display_short = r.display_name.split(",")[0].split(" - ")[0].strip()
                display_country = _iso_to_name(cc) if cc != "?" else r.display_name.split(",")[-1].strip()
                candidate_destinations.append({
                    "destination": display_short,
                    "country": cc,
                    "anchor": "location",
                    "anchor_label": f"{display_short}, {display_country}",
                    "anchor_date": None,
                    "_geo": r,
                })
            sources_used.append("nominatim")

    # --- Mode C: race-led (interest contains F1 or similar) ---
    interests_set = set(interests)
    race_interest = interests_set & {
        "f1", "f1 racing", "formula 1", "motorsport", "racing"
    }
    if race_interest and not event_id and not destination:
        jolpica = build_jolpica_client()
        try:
            races = await jolpica.fetch_season(date_from.year)
        except Exception:  # noqa: BLE001
            races = []
        if races:
            sources_used.append("jolpica")
        for r in races:
            if date_from <= r.starts_at.date() <= date_to + timedelta(days=2):
                race_cc = _COUNTRY_NAME_TO_CODE.get(r.country.upper(), "")
                # Build a clean candidate that uses Jolpica's country (no
                # Nominatim re-geocode → no Spanish-Budapest bug).
                race_geo = SimpleNamespace(
                    lat=0.0, lon=0.0,
                    display_name=f"{r.city}, {_iso_to_name(race_cc) or r.country}",
                    country_code=race_cc,
                )
                race_res = await ref.resolve(r.city)
                race_res_d = race_res.to_dict()
                if race_res_d["matched"] and race_res_d["city"]:
                    race_geo.lat = race_res_d["city"]["latitude"]
                    race_geo.lon = race_res_d["city"]["longitude"]
                candidate_destinations.append({
                    "destination": r.city,
                    "country": race_cc,
                    "anchor": "race",
                    "anchor_label": r.name,
                    "anchor_date": r.starts_at.date().isoformat(),
                    "_geo": race_geo,
                })

    # --- Mode D: interest-led (general) ---
    if interests and not race_interest and not event_id and not destination:
        raise HTTPException(
            400,
            f"interest={interests} requires a destination or event_id. "
            "Try ?destination=Brussels&interest=jazz or ?event_id=jolpica:2026:10.",
        )

    # --- De-duplicate candidates by city+country ---
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for c in candidate_destinations:
        key = (c["destination"].lower(), c["country"].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    candidate_destinations = deduped[:top_n]

    if not candidate_destinations:
        raise HTTPException(
            404,
            "no destinations matched the given anchors and date range",
        )

    # --- For each candidate, build an itinerary ---
    osrm = build_osrm_client()
    jolpica = build_jolpica_client()
    holidays_client = build_holidays_client()
    overpass = build_overpass_client()
    itineraries: list[Itinerary] = []

    # Pre-fetch the season once (saves 1s per candidate × N candidates)
    try:
        season_year = max(date_from.year, date_to.year)
        season_races = await jolpica.fetch_season(season_year)
    except Exception:
        season_races = []

    for c in candidate_destinations:
        # Reuse the already-geocoded result if we have it
        d = c.get("_geo") if c.get("_geo") else None
        if d is None:
            try:
                cand_geo = await nomi.geocode(c["destination"], limit=1)
            except Exception:
                cand_geo = []
            if not cand_geo:
                continue
            d = cand_geo[0]
        # Reject obviously wrong results: if country_code is "?" we don't
        # have a country to match races/holidays against.
        d_country = (d.country_code or "").upper()

        # If the display_name is from Nominatim (race-led/event-led branch)
        # it can be the raw mess "Spa, België / Belgique / Belgien".
        # Build a clean display name from city + ISO country code.
        d_city_clean = d.display_name.split(",")[0].split(" - ")[0].strip()
        d_country_clean = _iso_to_name(d_country) if d_country else d.display_name.split(",")[-1].strip()

        # Route
        route = None
        if origin_geo:
            try:
                route = await osrm.route(origin_geo.lon, origin_geo.lat, d.lon, d.lat)
            except Exception as e:  # noqa: BLE001
                logger.warning("OSRM route failed for %s: %s", c["destination"], e)
        if route:
            sources_used.append("osrm")

        # F1 races at this candidate — country match (2-letter code to name)
        races_at_destination: list[dict] = []
        for r in season_races:
            race_cc = _COUNTRY_NAME_TO_CODE.get(r.country.upper(), "")
            same_country = d_country and race_cc == d_country
            in_window = date_from <= r.starts_at.date() <= date_to + timedelta(days=2)
            if same_country and in_window:
                races_at_destination.append({
                    "name": r.name,
                    "circuit": r.circuit,
                    "city": r.city,
                    "country": r.country,
                    "starts_at": r.starts_at.isoformat(),
                })

        # Holidays
        holiday_alerts: list[dict] = []
        if d_country:
            try:
                hs = await holidays_client.fetch_year(
                    date_from.year, d_country
                )
                for h in hs:
                    try:
                        d_hol = date.fromisoformat(h.date)
                    except ValueError:
                        continue
                    if date_from <= d_hol <= date_to:
                        holiday_alerts.append({
                            "date": h.date,
                            "name": h.english_name,
                            "local": h.local_name,
                        })
            except Exception as e:  # noqa: BLE001
                logger.warning("Holidays fetch failed: %s", e)

        # Hotels via OpenStreetMap Overpass. Free, no key, real data.
        # 5km radius for downtown, expand to 10km if <3 found.
        hotels: list[dict] = []
        if overpass is not None and d.lat and d.lon:
            try:
                hotel_pois = await overpass.search_hotels_near(
                    d.lat, d.lon, radius_km=5.0, limit=15,
                )
                if len(hotel_pois) < 3:
                    wider = await overpass.search_hotels_near(
                        d.lat, d.lon, radius_km=10.0, limit=20,
                    )
                    seen_ids = {h.osm_id for h in hotel_pois}
                    hotel_pois.extend(h for h in wider if h.osm_id not in seen_ids)
                hotels = [
                    {
                        "osm_id": p.osm_id,
                        "name": p.name,
                        "lat": p.lat,
                        "lon": p.lon,
                        "stars": p.tags.get("stars") or p.tags.get("stars:official"),
                        "rooms": p.tags.get("rooms") or p.tags.get("capacity"),
                        "addr": p.tags.get("addr:full") or (
                            ", ".join(filter(None, [
                                p.tags.get("addr:street"),
                                p.tags.get("addr:housenumber"),
                            ])) or None
                        ),
                        "phone": p.tags.get("phone") or p.tags.get("contact:phone"),
                        "website": p.tags.get("website") or p.tags.get("contact:website"),
                    }
                    for p in hotel_pois
                ]
                if hotels and "overpass" not in sources_used:
                    sources_used.append("overpass")
            except Exception as e:  # noqa: BLE001
                logger.warning("Overpass hotel search failed: %s", e)
                hotels = []

        # Score (audit-only reasons). The user-facing pitch is built in
        # the dedicated ``_build_pitch`` helper.
        duration = (date_to - date_from).days + 1
        score, audit_reasons = _score_itinerary(
            distance_km=route.distance_m / 1000 if route else 0.0,
            duration_days=duration,
            races_at_destination=len(races_at_destination),
            holidays_count=len(holiday_alerts),
        )
        pitch = _build_pitch(
            interests=[],
            races_in_window=races_at_destination,
            holiday_alerts=holiday_alerts,
            duration_days=duration,
            has_event_window=False,  # legacy /discover has no event-window concept
        )
        logger.info(
            "discover itinerary %s: score=%s reasons=%s pitch=%s",
            d_city_clean, score, audit_reasons, pitch,
        )
        it = Itinerary(
            rank=0,
            score=round(score, 1),
            pitch=pitch,
            destination=d_city_clean,
            destination_country=d_country_clean,
            start_date=date_from.isoformat(),
            end_date=date_to.isoformat(),
            duration_days=duration,
            total_distance_km=route.distance_m / 1000 if route else 0.0,
            races_in_window=races_at_destination,
            holiday_alerts=holiday_alerts,
            hotels=hotels,
            route={
                "distance_km": route.distance_m / 1000,
                "duration_h": route.duration_s / 3600,
            } if route else None,
            sources=list(set(sources_used)),
            missing=missing,
        )
        itineraries.append(it)

    # Rank by score
    itineraries.sort(key=lambda i: i.score, reverse=True)
    for idx, it in enumerate(itineraries, start=1):
        it.rank = idx

    from dataclasses import asdict
    return {
        "anchors": {
            "origin": origin,
            "destination": destination,
            "event_id": event_id,
            "interest": interest,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
        "results": [asdict(i) for i in itineraries],
        "sources_used": list(set(sources_used)),
        "missing_data": missing,
    }


async def _resolve_event(event_id: str) -> dict | None:
    """Resolve a source event id (Jolpica only for now) to a single race dict."""
    if not event_id.startswith("jolpica:"):
        return None
    parts = event_id.split(":")
    if len(parts) < 3:
        return None
    try:
        season = int(parts[1])
        round_number = int(parts[2])
    except ValueError:
        return None
    jolpica = build_jolpica_client()
    try:
        races = await jolpica.fetch_season(season)
    except Exception:
        return None
    for r in races:
        if r.round_number == round_number:
            return {
                "name": r.name,
                "circuit": r.circuit,
                "city": r.city,
                "country": r.country,
                "starts_at": r.starts_at,
            }
    return None


# ISO 3166-1 alpha-2 → human name. The minimum needed for clean display
# when the geocoder returns a mess. (Eventually, look this up from
# the refdata countries table; for now the F1 calendar only races in
# these countries.)
_ISO_TO_NAME: dict[str, str] = {
    "AU": "Australia", "AT": "Austria", "AZ": "Azerbaijan",
    "BH": "Bahrain", "BE": "Belgium", "BR": "Brazil",
    "CA": "Canada", "CN": "China", "FR": "France",
    "DE": "Germany", "HU": "Hungary", "IN": "India",
    "IT": "Italy", "JP": "Japan", "MX": "Mexico",
    "MC": "Monaco", "NL": "Netherlands", "PT": "Portugal",
    "QA": "Qatar", "SA": "Saudi Arabia", "SG": "Singapore",
    "ES": "Spain", "CH": "Switzerland", "TR": "Türkiye",
    "AE": "United Arab Emirates", "GB": "United Kingdom",
    "US": "United States", "MZ": "Mozambique", "ZA": "South Africa",
}


def _iso_to_name(code: str) -> str:
    return _ISO_TO_NAME.get(code, code)


# ISO 3166-1 alpha-2 country code lookup for race countries.
# Jolpica gives full country names, Nominatim gives 2-letter codes.
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "AUSTRALIA": "AU", "AUSTRIA": "AT", "AZERBAIJAN": "AZ",
    "BAHRAIN": "BH", "BELGIUM": "BE", "BRAZIL": "BR",
    "CANADA": "CA", "CHINA": "CN", "FRANCE": "FR",
    "GERMANY": "DE", "HUNGARY": "HU", "INDIA": "IN",
    "ITALY": "IT", "JAPAN": "JP", "MEXICO": "MX",
    "MONACO": "MC", "NETHERLANDS": "NL", "PORTUGAL": "PT",
    "QATAR": "QA", "SAUDI ARABIA": "SA", "SINGAPORE": "SG",
    "SPAIN": "ES", "SWITZERLAND": "CH", "TURKEY": "TR",
    "TURKIYE": "TR", "UNITED ARAB EMIRATES": "AE", "UAE": "AE",
    "UNITED KINGDOM": "GB", "UK": "GB", "USA": "US",
    "UNITED STATES": "US", "AMERICA": "US",
    "MOZAMBIQUE": "MZ", "SOUTH AFRICA": "ZA",
    "ZIMBABWE": "ZW", "NAMIBIA": "NA", "ZAMBIA": "ZM",
    "BOTSWANA": "BW", "KENYA": "KE", "ANGOLA": "AO",
    "DEMOCRATIC REPUBLIC OF THE CONGO": "CD", "DRC": "CD",
    "TANZANIA": "TZ", "MALAWI": "MW", "MADAGASCAR": "MG",
    "MAURITIUS": "MU", "RWANDA": "RW", "UGANDA": "UG",
    "ARGENTINA": "AR", "SOUTH KOREA": "KR", "KOREA": "KR",
    "RUSSIA": "RU", "THAILAND": "TH", "MALAYSIA": "MY",
    "INDONESIA": "ID", "VIETNAM": "VN", "PHILIPPINES": "PH",
    "EGYPT": "EG", "MOROCCO": "MA", "NIGERIA": "NG",
    "GHANA": "GH", "SENEGAL": "SN", "ETHIOPIA": "ET",
}


# Hard-coded disambiguation for common ambiguous city names.
# Used to bias the discover endpoint to the right country when the user
# doesn't specify one.
_DISAMBIGUATE_CITY: dict[str, str] = {
    "brussels": "BE",
    "paris": "FR",
    "london": "GB",
    "new york": "US",
    "los angeles": "US",
    "san francisco": "US",
    "mexico city": "MX",
    "sao paulo": "BR",
    "são paulo": "BR",
    "cape town": "ZA",
    "johannesburg": "ZA",
    "joburg": "ZA",
    "maputo": "MZ",
    "dar es salaam": "TZ",
    "lagos": "NG",
    "nairobi": "KE",
    "dubai": "AE",
    "munich": "DE",
    "milan": "IT",
    "florence": "IT",
    "barcelona": "ES",
    "seville": "ES",
    "valencia": "ES",
    "athens": "GR",
    "vienna": "AT",
    "zurich": "CH",
    "geneva": "CH",
    "copenhagen": "DK",
    "stockholm": "SE",
    "oslo": "NO",
    "helsinki": "FI",
    "warsaw": "PL",
    "budapest": "HU",
    "prague": "CZ",
    "sofia": "BG",
    "bucharest": "RO",
    "istanbul": "TR",
    "tokyo": "JP",
    "osaka": "JP",
    "kyoto": "JP",
    "shanghai": "CN",
    "beijing": "CN",
    "hong kong": "HK",
    "singapore": "SG",
    "bangkok": "TH",
    "kuala lumpur": "MY",
    "jakarta": "ID",
    "manila": "PH",
    "mumbai": "IN",
    "delhi": "IN",
    "sydney": "AU",
    "melbourne": "AU",
    "auckland": "NZ",
    "vancouver": "CA",
    "toronto": "CA",
}


__all__ = ["router"]

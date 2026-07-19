"""Public refdata router: serves countries, cities, airports, and a
free-text resolver. Used by the landing page to render the real city
chip list and by the discover flow to canonicalise user input."""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.refdata.models import Airport, City, Country
from app.refdata.service import ReferenceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/refdata", tags=["refdata"])


# -----------------------------------------------------------------------------
# Countries
# -----------------------------------------------------------------------------

@router.get("/countries")
async def list_countries(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    svc = ReferenceService(session)
    countries = await svc.list_countries()
    return {
        "items": [
            {
                "alpha2": c.alpha2,
                "alpha3": c.alpha3,
                "name": c.name,
                "name_pt": c.name_pt,
                "currency": c.currency,
                "flag_emoji": c.flag_emoji,
                "languages": c.languages.split(",") if c.languages else [],
            }
            for c in countries
        ],
        "count": len(countries),
    }


# -----------------------------------------------------------------------------
# Cities
# -----------------------------------------------------------------------------

@router.get("/cities")
async def list_cities(
    session: Annotated[AsyncSession, Depends(get_session)],
    country: str | None = Query(None, description="ISO alpha-2 filter, e.g. 'BE'"),
    limit: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    svc = ReferenceService(session)
    cities = await svc.list_cities(country_alpha2=country, limit=limit)
    return {
        "items": [
            {
                "id": str(c.id),
                "name": c.name,
                "ascii_name": c.ascii_name,
                "country_alpha2": c.country_alpha2,
                "country_name": c.country.name if c.country else None,
                "region": c.region,
                "latitude": c.latitude,
                "longitude": c.longitude,
                "timezone": c.timezone,
                "is_capital": c.is_capital,
                "primary_iata": c.airports[0].iata if c.airports else None,
                "airports": [
                    {
                        "iata": a.iata,
                        "icao": a.icao,
                        "name": a.name,
                        "short_name": a.short_name,
                        "priority": a.priority,
                    }
                    for a in (c.airports or [])
                ],
            }
            for c in cities
        ],
        "count": len(cities),
    }


# -----------------------------------------------------------------------------
# Airports
# -----------------------------------------------------------------------------

@router.get("/airports/{iata}")
async def get_airport(
    iata: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    svc = ReferenceService(session)
    ap = await svc.get_airport(iata)
    if ap is None:
        raise HTTPException(status_code=404, detail=f"airport {iata!r} not found")
    return {
        "iata": ap.iata,
        "icao": ap.icao,
        "name": ap.name,
        "short_name": ap.short_name,
        "kind": ap.kind,
        "latitude": ap.latitude,
        "longitude": ap.longitude,
        "priority": ap.priority,
        "is_active": ap.is_active,
        "city": {
            "id": str(ap.city.id),
            "name": ap.city.name,
            "ascii_name": ap.city.ascii_name,
            "country_alpha2": ap.city.country_alpha2,
            "country_name": ap.city.country.name if ap.city.country else None,
        } if ap.city else None,
    }


# -----------------------------------------------------------------------------
# Free-text resolver
# -----------------------------------------------------------------------------

@router.get("/resolve")
async def resolve(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: str = Query(..., min_length=1, max_length=200),
    country: str | None = Query(None, description="ISO alpha-2 bias, e.g. 'BE'"),
) -> dict[str, Any]:
    """Resolve any free-text or code to a structured location.

    Examples:
      /resolve?q=joburg            → Johannesburg, ZA
      /resolve?q=brussels&country=BE → Brussels, BE (not the US town)
      /resolve?q=BRU               → Brussels Airport
      /resolve?q=Sao+Paulo         → São Paulo, BR
      /resolve?q=or+tambo          → Johannesburg (via OR Tambo)
    """
    svc = ReferenceService(session)
    res = await svc.resolve(q, country_bias=country)
    return res.to_dict()


# -----------------------------------------------------------------------------
# Booking link builder (uses Airport table IATA codes)
# -----------------------------------------------------------------------------

def _build_flight_links(
    from_iata: str | None,
    to_iata: str | None,
    depart_iso: str | None,
    return_iso: str | None = None,
    *,
    fallback_query: str | None = None,
) -> dict[str, str]:
    """Build outbound deep links for the major travel search engines.

    All links open in a new tab. If an IATA code is missing we fall back
    to a Google Flights text search so the user always gets a result.
    """
    import urllib.parse

    if not depart_iso:
        depart_iso = ""
    depart_compact = depart_iso.replace("-", "") if depart_iso else ""

    if from_iata and to_iata:
        # Google Flights: flights?q=from+IATA+to+IATA+on+DATE
        gf = f"https://www.google.com/travel/flights?q=flights%20from%20{from_iata}%20to%20{to_iata}%20on%20{depart_iso}"
        # Skyscanner: /transport/flights/IATA/IATA/YYMMDD/
        sk_url = f"https://www.skyscanner.com/transport/flights/{from_iata.lower()}/{to_iata.lower()}/{depart_compact}/"
        links = {
            "google_flights": gf,
            "skyscanner": sk_url,
        }
    else:
        q = fallback_query or "flights"
        links = {
            "google_flights": f"https://www.google.com/travel/flights?q={urllib.parse.quote(q)}",
        }
    return links


def _build_hotel_links(
    city_name: str | None,
    checkin_iso: str | None,
    checkout_iso: str | None,
) -> dict[str, str]:
    """Build outbound hotel/accommodation deep links."""
    if not city_name:
        return {}
    cn = urllib_quote(city_name)
    if checkin_iso and checkout_iso:
        bk = f"https://www.booking.com/searchresults.html?ss={cn}&checkin={checkin_iso}&checkout={checkout_iso}"
        ag = f"https://www.agoda.com/search?city={cn}&checkIn={checkin_iso}&checkOut={checkout_iso}"
    else:
        bk = f"https://www.booking.com/searchresults.html?ss={cn}"
        ag = f"https://www.agoda.com/search?city={cn}"
    return {"booking_com": bk, "agoda": ag}


def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)


__all__ = ["router", "_build_flight_links", "_build_hotel_links"]

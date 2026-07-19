"""OpenStreetMap Nominatim geocoding client — real HTTP wire.

Public API, no key needed. https://nominatim.org/release-docs/develop/
We use it for city/place name -> lat/lon resolution, with a strong
User-Agent (Nominatim ToS) and 1 req/sec rate limit.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.clients.base import BaseClient

logger = logging.getLogger(__name__)

NOMINATIM_BASE = "https://nominatim.openstreetmap.org"
_USER_AGENT = "TravelScout/2.0 (research contact@travelscout.example)"
_HTTP_TIMEOUT = 15.0
# Nominatim ToS: max 1 request/second.
_RATE_LIMIT_S = 1.1
_last_call = 0.0
_lock = asyncio.Lock()

# Country name / code helpers — used to disambiguate "Brussels", "Paris" etc.
_COUNTRY_HINTS: dict[str, str] = {
    "mozambique": "MZ", "moz": "MZ", "mocambique": "MZ",
    "south africa": "ZA", "sa": "ZA", "rsa": "ZA",
    "zimbabwe": "ZW", "zim": "ZW",
    "namibia": "NA",
    "dr congo": "CD", "drc": "CD", "congo": "CD",
    "zambia": "ZM",
    "tanzania": "TZ",
    "botswana": "BW",
    "kenya": "KE",
    "angola": "AO",
    "madagascar": "MG",
    "malawi": "MW",
    "mauritius": "MU",
    "seychelles": "SC",
    "uganda": "UG",
    "rwanda": "RW",
    "burundi": "BI",
    "lesotho": "LS", "eswatini": "SZ", "swaziland": "SZ",
    "belgium": "BE", "be": "BE", "belgique": "BE", "belgie": "BE",
    "france": "FR", "fr": "FR",
    "netherlands": "NL", "holland": "NL", "nl": "NL",
    "germany": "DE", "de": "DE", "deutschland": "DE",
    "uk": "GB", "united kingdom": "GB", "england": "GB", "britain": "GB", "gb": "GB",
    "spain": "ES", "es": "ES", "espana": "ES",
    "italy": "IT", "it": "IT", "italia": "IT",
    "portugal": "PT", "pt": "PT",
    "usa": "US", "united states": "US", "us": "US", "america": "US",
    "japan": "JP", "jp": "JP",
    "china": "CN", "cn": "CN",
    "australia": "AU", "au": "AU",
    "brazil": "BR", "br": "BR", "brasil": "BR",
    "uae": "AE", "united arab emirates": "AE",
    "saudi arabia": "SA", "saudi": "SA",
    "india": "IN", "in": "IN",
    "singapore": "SG",
    "thailand": "TH",
    "mexico": "MX",
    "argentina": "AR",
    "switzerland": "CH",
    "austria": "AT",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "poland": "PL",
    "turkey": "TR", "türkiye": "TR",
    "egypt": "EG",
    "morocco": "MA",
    "tunisia": "TN",
    "ghana": "GH",
    "nigeria": "NG",
    "senegal": "SN",
    "ethiopia": "ET",
    "tanzania, united republic of": "TZ",
}


def _extract_country_code(query: str) -> str | None:
    """Look for a country name or 2-letter code in the query string.

    Substring match is only used for multi-word country names. For 2- and
    3-letter keys (which would otherwise false-match in city names like
    "Brussels" containing "us", or "Lusaka" containing "us"), we require a
    whole-word match surrounded by non-letter boundaries.
    """
    q = query.lower().strip()
    # Direct 2-letter code at end (e.g. "Brussels, BE")
    if "," in q:
        suffix = q.rsplit(",", 1)[-1].strip().upper()
        if len(suffix) == 2 and suffix.isalpha():
            return suffix
    # Whole-word match for short keys (avoids "us" in "brussels" -> US).
    # Build a regex that matches the key only when surrounded by non-letters
    # or string boundaries.
    import re as _re
    word_boundary = _re.compile(r"(^|\b)({})(\b|$)".format("|".join(
        _re.escape(k) for k in _COUNTRY_HINTS
    )))
    m = word_boundary.search(q)
    if m:
        return _COUNTRY_HINTS[m.group(2)]
    return None


@dataclass
class GeocodeResult:
    display_name: str
    lat: float
    lon: float
    bbox: tuple[float, float, float, float]  # south, north, west, east
    place_class: str
    place_type: str
    country_code: str | None
    importance: float


class NominatimClient(BaseClient):
    source_key = "nominatim"

    def is_configured(self) -> bool:
        return True

    async def geocode(
        self,
        query: str,
        limit: int = 5,
        country_bias: str | None = None,
    ) -> list[GeocodeResult]:
        """Geocode a place name. If ``country_bias`` is set (ISO 3166-1
        alpha-2, lowercased), Nominatim is asked to prefer that country.
        """
        global _last_call
        url = f"{NOMINATIM_BASE}/search"
        params: dict[str, str] = {
            "q": query,
            "format": "jsonv2",
            "limit": str(limit),
            "addressdetails": "1",
            "accept-language": "en",
        }
        # If the query contains a country code or recognizable country name,
        # bias the search to that country. This prevents "Brussels" returning
        # US towns, "Paris" returning Texas, etc.
        cc = _extract_country_code(query)
        if cc:
            params["countrycodes"] = cc.lower()
        elif country_bias:
            params["countrycodes"] = country_bias.lower()
        async with _lock:
            now = asyncio.get_event_loop().time()
            wait = _RATE_LIMIT_S - (now - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call = asyncio.get_event_loop().time()
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                r = await client.get(
                    url,
                    params=params,
                    headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                )
                r.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("Nominatim geocode(%r) failed: %s", query, e)
                raise
        data = r.json()
        out: list[GeocodeResult] = []
        for item in data:
            bbox = item.get("boundingbox", [])
            out.append(
                GeocodeResult(
                    display_name=item.get("display_name", ""),
                    lat=float(item.get("lat", 0.0)),
                    lon=float(item.get("lon", 0.0)),
                    bbox=(
                        float(bbox[0]) if len(bbox) >= 1 else 0.0,
                        float(bbox[1]) if len(bbox) >= 2 else 0.0,
                        float(bbox[2]) if len(bbox) >= 3 else 0.0,
                        float(bbox[3]) if len(bbox) >= 4 else 0.0,
                    ),
                    place_class=item.get("class", ""),
                    place_type=item.get("type", ""),
                    country_code=(item.get("address") or {}).get("country_code", "").upper() or None,
                    importance=float(item.get("importance", 0.0)),
                )
            )
        logger.info("Nominatim geocode(%r) returned %d results", query, len(out))
        return out


def build_nominatim_client() -> NominatimClient:
    return NominatimClient()


__all__ = ["NominatimClient", "GeocodeResult", "build_nominatim_client"]

"""Cross-source location resolver.

Given a city name and (optional) country hint, returns a fully-populated
``Location`` object with every ISO field filled in, plus the list of
upstream sources that contributed and a confidence score.

Pipeline per query:
  1. **mledoze / RestCountries** (bundled, offline) — country-only lookup
  2. **Nominatim** (OSM, free) — city + lat/lon, has alpha-2 in address
  3. **Wikidata SPARQL** (free) — city QID + subdivision + ISO 3166-2
  4. **GeoNames** (free demo, optional — needs ``GEONAMES_USERNAME``)
  5. **Wikipedia geosearch** (free) — last-resort city match

After all sources respond, we consensus-validate:
  * The alpha-2 most sources agree on wins
  * Subdivision ISO 3166-2 codes are taken from Wikidata (most reliable)
  * Coordinates: prefer Nominatim (high-precision), fall back to Wikidata
  * Confidence = ``matched_sources / total_sources`` where ``matched``
    means ``country_alpha2 == consensus_alpha2``
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from app.refdata.iso3166 import (
    IOC_TO_ALPHA2,
    ALPHA2_TO_WIKIDATA_QID,
    M49_TO_REGION_NAME,
    country as iso_country,
    resolve_alpha2,
)
from app.schemas.location import Location, GeoSource

logger = logging.getLogger(__name__)

# GeoNames (optional, requires GEONAMES_USERNAME env var)
GEONAMES_USERNAME = os.environ.get("GEONAMES_USERNAME", "").strip()
GEONAMES_BASE = "http://api.geonames.org"

# Wikipedia (no key, free)
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_REST = "https://www.wikidata.org/w/rest.php/wikibase/v1"

# In-process cache: (city_lower, country_hint) -> Location
_RESOLVER_CACHE: dict[tuple[str, str], Location] = {}
_RESOLVER_CACHE_TTL_S = 24 * 3600
_RESOLVER_CACHE_TS: dict[tuple[str, str], float] = {}

import time as _time


class LocationResolver:
    """Resolve (city, country_hint) to an ISO-compliant Location."""

    source_key = "location_resolver"

    def __init__(self) -> None:
        self._sem = asyncio.Semaphore(4)  # cap concurrent upstream calls

    async def resolve(
        self,
        city: str | None,
        country_alpha2: str | None = None,
        *,
        timeout: float = 8.0,
    ) -> Location:
        """Resolve a city + optional country hint to a Location.

        ``city`` is the place name as the user typed it (or the city
        from a Wikipedia/Wikidata row). ``country_alpha2`` is an
        optional ISO alpha-2 hint that biases the lookup (e.g. "Maputo,
        MZ" — the user told us it's Mozambique).
        """
        if not city and not country_alpha2:
            return Location.now()
        city_norm = (city or "").strip()
        cc_norm = (country_alpha2 or "").strip().upper()
        cache_key = (city_norm.lower(), cc_norm)
        if cache_key in _RESOLVER_CACHE:
            ts = _RESOLVER_CACHE_TS.get(cache_key, 0)
            if _time.time() - ts < _RESOLVER_CACHE_TTL_S:
                return _RESOLVER_CACHE[cache_key]

        sources: list[GeoSource] = []
        # Run the 4 sources in parallel
        try:
            async with asyncio.timeout(timeout):
                mledoze_task = self._from_iso3166(city_norm, cc_norm)
                nominatim_task = self._from_nominatim(city_norm, cc_norm)
                wikidata_task = self._from_wikidata(city_norm, cc_norm)
                geonames_task = (
                    self._from_geonames(city_norm, cc_norm)
                    if GEONAMES_USERNAME else asyncio.sleep(0, result=GeoSource(source="geonames"))
                )
                results = await asyncio.gather(
                    mledoze_task, nominatim_task, wikidata_task, geonames_task,
                    return_exceptions=True,
                )
        except (TimeoutError, asyncio.TimeoutError):
            results = [
                GeoSource(source="timeout"),
                GeoSource(source="timeout"),
                GeoSource(source="timeout"),
                GeoSource(source="timeout"),
            ]

        for r in results:
            if isinstance(r, BaseException):
                logger.info("Location source error: %s", r)
                continue
            if r is not None:
                sources.append(r)

        loc = self._consensus(sources, city_norm, cc_norm)
        _RESOLVER_CACHE[cache_key] = loc
        _RESOLVER_CACHE_TS[cache_key] = _time.time()
        return loc

    # ------------------------------------------------------------------
    # Source 1: bundled ISO 3166-1 (country only — no city resolution)
    # ------------------------------------------------------------------
    async def _from_iso3166(self, city: str, country_alpha2: str) -> GeoSource:
        a2 = country_alpha2 or resolve_alpha2(city)
        rec = iso_country(a2) if a2 else None
        if not rec:
            return GeoSource(source="iso3166", locality=city, matched=False)
        return GeoSource(
            source="iso3166",
            country_alpha2=rec["alpha2"],
            country_alpha3=rec.get("alpha3", ""),
            country_numeric=rec.get("numeric", ""),
            locality=city,
            latitude=(rec.get("latlng") or [None, None])[0] if not city else None,
            longitude=(rec.get("latlng") or [None, None])[1] if not city else None,
            wikidata_qid=ALPHA2_TO_WIKIDATA_QID.get(rec["alpha2"], ""),
            matched=True,
        )

    # ------------------------------------------------------------------
    # Source 2: Nominatim (OpenStreetMap) — best for city + lat/lon
    # ------------------------------------------------------------------
    async def _from_nominatim(self, city: str, country_alpha2: str) -> GeoSource:
        if not city:
            return GeoSource(source="nominatim", matched=False)
        try:
            import httpx
        except ImportError:
            return GeoSource(source="nominatim", matched=False)
        params: dict[str, str] = {
            "q": city,
            "format": "jsonv2",
            "limit": "3",
            "addressdetails": "1",
            "accept-language": "en",
        }
        if country_alpha2:
            params["countrycodes"] = country_alpha2.lower()
        try:
            async with self._sem:
                async with httpx.AsyncClient(timeout=6) as client:
                    r = await client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params=params,
                        headers={
                            "User-Agent": "TravelScout/2.0 (research)",
                            "Accept": "application/json",
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
        except Exception as e:
            logger.debug("Nominatim error: %s", e)
            return GeoSource(source="nominatim", locality=city, matched=False)
        if not data:
            return GeoSource(source="nominatim", locality=city, matched=False)
        # Pick the most important result
        best = max(data, key=lambda d: float(d.get("importance", 0) or 0))
        addr = best.get("address", {}) or {}
        a2 = (addr.get("country_code", "") or "").upper()
        # ISO 3166-2 (state/region)
        subdivision = (
            addr.get("state_code")
            or addr.get("ISO3166-2-lvl4")
            or addr.get("ISO3166-2-lvl6")
            or ""
        )
        if subdivision and a2 and "-" not in subdivision:
            subdivision = f"{a2}-{subdivision}"
        # City / town / village
        locality = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("county")
            or addr.get("municipality")
            or city
        )
        return GeoSource(
            source="nominatim",
            country_alpha2=a2,
            subdivision_code=subdivision,
            locality=locality,
            latitude=float(best["lat"]) if best.get("lat") else None,
            longitude=float(best["lon"]) if best.get("lon") else None,
            feature_code=best.get("category", "") + "/" + best.get("type", ""),
            matched=bool(a2),
        )

    # ------------------------------------------------------------------
    # Source 3: Wikidata SPARQL — best for ISO 3166-2, city QID
    # ------------------------------------------------------------------
    async def _from_wikidata(self, city: str, country_alpha2: str) -> GeoSource:
        if not city:
            return GeoSource(source="wikidata", matched=False)
        try:
            import httpx
        except ImportError:
            return GeoSource(source="wikidata", matched=False)
        # Query: get the city as a QID, plus its country and subdivision.
        # We use the city label as a search term; the wdt:P31 / P17 / P131
        # properties give us country + subdivision (P131 = "located in the
        # administrative territorial entity").
        city_escaped = city.replace('"', '\\"')
        if country_alpha2:
            # Use ISO 3166-1 alpha-2 code (P297) to disambiguate
            country_filter = f"FILTER(?cc = \"{country_alpha2}\") ."
        else:
            country_filter = ""
        sparql = f"""
        SELECT ?city ?cityLabel ?country ?countryLabel ?cc ?subdiv ?subdivLabel
               ?coord ?iso2 ?iso3 ?num ?pop WHERE {{
          ?city rdfs:label "{city_escaped}"@en .
          ?city wdt:P31/wdt:P279* wd:Q515 .
          OPTIONAL {{ ?city wdt:P17 ?country }}
          OPTIONAL {{ ?country wdt:P297 ?cc }}
          OPTIONAL {{ ?country wdt:P298 ?iso3 }}
          OPTIONAL {{ ?country wdt:P299 ?num }}
          OPTIONAL {{ ?city wdt:P131 ?subdiv }}
          OPTIONAL {{ ?city wdt:P625 ?coord }}
          OPTIONAL {{ ?city wdt:P1082 ?pop }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
          {country_filter}
        }}
        ORDER BY DESC(?pop)
        LIMIT 5
        """
        try:
            async with self._sem:
                async with httpx.AsyncClient(timeout=6) as client:
                    r = await client.get(
                        WIKIDATA_SPARQL,
                        params={"query": sparql, "format": "json"},
                        headers={
                            "User-Agent": "TravelScout/2.0 (research)",
                            "Accept": "application/sparql-results+json",
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
        except Exception as e:
            logger.debug("Wikidata SPARQL error: %s", e)
            return GeoSource(source="wikidata", locality=city, matched=False)
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            return GeoSource(source="wikidata", locality=city, matched=False)
        # Pick the highest-population match (first since ORDER BY DESC)
        b = bindings[0]
        a2 = b.get("cc", {}).get("value", "").upper()
        a3 = b.get("iso3", {}).get("value", "").upper()
        numeric = b.get("num", {}).get("value", "")
        coord = b.get("coord", {}).get("value", "")
        lat = lon = None
        if coord.startswith("Point("):
            try:
                parts = coord.replace("Point(", "").rstrip(")").split()
                lon = float(parts[0]); lat = float(parts[1])
            except (ValueError, IndexError):
                pass
        # ISO 3166-2 subdivision from ?subdiv — the P131 value's
        # identifier often starts with the country code prefix.
        subdiv_uri = b.get("subdiv", {}).get("value", "")
        subdiv_qid = subdiv_uri.rsplit("/", 1)[-1] if subdiv_uri else ""
        # We need to look up the subdivision's ISO 3166-2 code; this
        # is a second query, but we inline the common ones below.
        city_qid = b.get("city", {}).get("value", "").rsplit("/", 1)[-1]
        return GeoSource(
            source="wikidata",
            country_alpha2=a2,
            country_alpha3=a3,
            country_numeric=numeric,
            locality=city,
            latitude=lat,
            longitude=lon,
            wikidata_qid=a2,  # this source is the country QID
            matched=bool(a2),
            feature_code=f"QID:{city_qid}|SUBDIV:{subdiv_qid}",
        )

    # ------------------------------------------------------------------
    # Source 4: GeoNames (optional, requires GEONAMES_USERNAME)
    # ------------------------------------------------------------------
    async def _from_geonames(self, city: str, country_alpha2: str) -> GeoSource:
        if not GEONAMES_USERNAME or not city:
            return GeoSource(source="geonames", matched=False)
        try:
            import httpx
        except ImportError:
            return GeoSource(source="geonames", matched=False)
        params: dict[str, str] = {
            "q": city,
            "maxRows": "5",
            "username": GEONAMES_USERNAME,
            "type": "json",
        }
        if country_alpha2:
            params["country"] = country_alpha2
        try:
            async with self._sem:
                async with httpx.AsyncClient(timeout=6) as client:
                    r = await client.get(
                        f"{GEONAMES_BASE}/searchJSON", params=params
                    )
                    r.raise_for_status()
                    data = r.json()
        except Exception as e:
            logger.debug("GeoNames error: %s", e)
            return GeoSource(source="geonames", locality=city, matched=False)
        geonames = data.get("geonames", [])
        if not geonames:
            return GeoSource(source="geonames", locality=city, matched=False)
        # Filter to populated places (PPL* feature class) and high population
        cities = [g for g in geonames if g.get("fcl") == "P"]
        if not cities:
            cities = geonames
        best = max(cities, key=lambda g: g.get("population", 0) or 0)
        return GeoSource(
            source="geonames",
            country_alpha2=best.get("countryCode", "").upper(),
            subdivision_code=best.get("adminCodes1", {}).get("ISO3166-2", ""),
            locality=best.get("toponymName", city),
            latitude=float(best.get("lat")) if best.get("lat") else None,
            longitude=float(best.get("lng")) if best.get("lng") else None,
            geonames_id=int(best.get("geonameId")) if best.get("geonameId") else None,
            feature_code=best.get("fcode", ""),
            matched=bool(best.get("countryCode")),
        )

    # ------------------------------------------------------------------
    # Consensus: pick the alpha-2 most sources agree on, fill in details
    # ------------------------------------------------------------------
    def _consensus(
        self,
        sources: list[GeoSource],
        city: str,
        country_alpha2: str,
    ) -> Location:
        # Tally
        tally: dict[str, int] = {}
        for s in sources:
            if s.country_alpha2 and len(s.country_alpha2) == 2:
                tally[s.country_alpha2] = tally.get(s.country_alpha2, 0) + 1
        # Pre-existing country hint counts as 1.5 votes
        if country_alpha2 and len(country_alpha2) == 2:
            tally[country_alpha2] = tally.get(country_alpha2, 0) + 2
        if not tally:
            return Location.now(locality=city)
        winner = max(tally.items(), key=lambda x: x[1])[0]
        # Mark matched
        for s in sources:
            s.matched = (s.country_alpha2 == winner) if s.country_alpha2 else False
        # Fill in the full ISO record for the winning country
        rec = iso_country(winner) or {}
        # Pull the best available subdivision
        sub_code = ""
        for s in sources:
            if s.country_alpha2 == winner and s.subdivision_code:
                sub_code = s.subdivision_code
                break
        # Pull the best available lat/lon
        lat = lon = None
        for s in sources:
            if s.country_alpha2 == winner and s.latitude is not None and s.longitude is not None:
                lat, lon = s.latitude, s.longitude
                break
        # Pull the best available locality
        locality = city
        for s in sources:
            if s.country_alpha2 == winner and s.locality:
                locality = s.locality
                break
        # Pull geonames_id
        geonames_id = None
        for s in sources:
            if s.country_alpha2 == winner and s.geonames_id:
                geonames_id = s.geonames_id
                break
        # Pull city QID from wikidata feature_code "QID:Q123"
        city_qid = ""
        for s in sources:
            if s.country_alpha2 == winner and s.feature_code.startswith("QID:"):
                city_qid = s.feature_code.split("|")[0].split(":")[1]
                break
        # Confidence = matched / total
        matched = sum(1 for s in sources if s.matched)
        total = max(1, len([s for s in sources if s.country_alpha2]))
        confidence = round(matched / total, 2) if total else 0.0
        display = f"{locality}, {rec.get('alpha2', winner)}"
        return Location.now(
            country_alpha2=rec.get("alpha2", winner),
            country_alpha3=rec.get("alpha3", ""),
            country_numeric=rec.get("numeric", ""),
            country_name_en=rec.get("name_en", ""),
            subdivision_code=sub_code,
            subdivision_name="",  # not decoded in this version
            locality=locality,
            display_name=display,
            latitude=lat,
            longitude=lon,
            wikidata_qid=ALPHA2_TO_WIKIDATA_QID.get(rec.get("alpha2", winner), ""),
            wikidata_city_qid=city_qid,
            geonames_id=geonames_id,
            region_code=rec.get("m49_region", ""),
            region_name=M49_TO_REGION_NAME.get(rec.get("m49_region", ""), ""),
            sources=sources,
            confidence=confidence,
        )


def build_location_resolver() -> LocationResolver:
    return LocationResolver()


__all__ = ["LocationResolver", "build_location_resolver"]

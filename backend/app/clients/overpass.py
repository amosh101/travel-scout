"""OpenStreetMap Overpass API client — real HTTP wire for POI search.

Public API, no key needed. https://wiki.openstreetmap.org/wiki/Overpass_API
We use it for hotel/restaurant/attraction search as POI, in lieu of a paid
hotel API. POST requests (ToS); the `data` field is the Overpass-QL query.

Latency: per-mirror HTTP timeout is 6s, fail-fast across 3 mirrors.
In-process cache (24h TTL) so repeated searches against the same city
don't hammer the mirrors. OSM POI data changes on the order of days.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from app.clients.base import BaseClient

logger = logging.getLogger(__name__)

# Public Overpass mirrors; primary first, then fallbacks.
_OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
_HTTP_TIMEOUT = 4.0  # per-mirror; bounded so user latency stays sane
_lock = asyncio.Lock()
# Be a good citizen: 1 req/sec across all mirrors.
_RATE_LIMIT_S = 1.0
_last_call = 0.0

# In-process cache for Overpass responses. Key is the query string;
# value is the raw JSON the API returned. 24h TTL — OSM POI data
# changes on the order of days, not seconds.
_OVERPASS_CACHE: dict[tuple, tuple[float, dict]] = {}
_OVERPASS_TTL_S = 24 * 3600


@dataclass
class POI:
    osm_id: int
    osm_type: str
    name: str
    lat: float
    lon: float
    category: str  # hotel, restaurant, attraction
    tags: dict[str, str]


class OverpassClient(BaseClient):
    source_key = "overpass"

    def is_configured(self) -> bool:
        return True

    async def _post(self, query: str) -> dict:
        # Best-effort cache by query string. Identical queries (same
        # downtown coord, same radius) return the same JSON for 24h.
        cache_key = ("query", query)
        now = time.time()
        cached = _OVERPASS_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _OVERPASS_TTL_S:
            logger.info("Overpass cache hit (query len=%d)", len(query))
            return cached[1]

        global _last_call
        async with _lock:
            now = asyncio.get_event_loop().time()
            wait = _RATE_LIMIT_S - (now - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call = asyncio.get_event_loop().time()
        # Try all mirrors in parallel — the first one to return wins.
        # Bound total wait to ~_HTTP_TIMEOUT instead of N × _HTTP_TIMEOUT.
        import asyncio as _aio
        async def _try(mirror: str) -> dict | None:
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    r = await client.post(
                        mirror,
                        data={"data": query},
                        headers={"User-Agent": "TravelScout/2.0"},
                    )
                    r.raise_for_status()
                    return r.json()
            except httpx.HTTPError as e:
                logger.warning("Overpass mirror %s failed: %s", mirror, e)
                return None
        tasks = [_aio.create_task(_try(m)) for m in _OVERPASS_MIRRORS]
        try:
            done, pending = await _aio.wait(
                tasks, return_when=_aio.FIRST_COMPLETED, timeout=_HTTP_TIMEOUT,
            )
            for t in done:
                if t.exception() is None and t.result() is not None:
                    data = t.result()
                    _OVERPASS_CACHE[cache_key] = (time.time(), data)
                    # Cancel remaining mirrors — we have our answer.
                    for p in pending:
                        p.cancel()
                    return data
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
        raise RuntimeError("all Overpass mirrors failed or timed out")

    @staticmethod
    def _parse_pois(data: dict, *, category: str) -> list[POI]:
        """Convert Overpass response elements into ``POI`` records.

        Honest about data: if a node has no ``name`` tag, we still keep
        the record but mark it as ``(unnamed)`` — the frontend can then
        decide whether to show or hide it. We never fabricate a name.
        """
        pois: list[POI] = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:en") or "(unnamed)"
            pois.append(
                POI(
                    osm_id=int(el.get("id", 0)),
                    osm_type=el.get("type", "node"),
                    name=name,
                    lat=float(el.get("lat", 0.0)),
                    lon=float(el.get("lon", 0.0)),
                    category=category,
                    tags=tags,
                )
            )
        return pois

    async def _search_in_bbox(
        self,
        tourism_kind: str,
        south: float, west: float, north: float, east: float,
        limit: int,
    ) -> list[POI]:
        q = (
            f"[out:json][timeout:20];"
            f"node[\"tourism\"=\"{tourism_kind}\"]({south},{west},{north},{east});"
            f"out {limit};"
        )
        data = await self._post(q)
        pois = self._parse_pois(data, category=tourism_kind)
        logger.info(
            "Overpass _search_in_bbox(%s) found %d", tourism_kind, len(pois),
        )
        return pois

    async def search_hotels_in_bbox(
        self, south: float, west: float, north: float, east: float, limit: int = 20,
    ) -> list[POI]:
        """Find hotels (`tourism=hotel`) within a bounding box."""
        return await self._search_in_bbox(
            "hotel", south, west, north, east, limit,
        )

    async def search_hotels_near(
        self, lat: float, lon: float, radius_km: float = 5.0, limit: int = 20,
    ) -> list[POI]:
        """Find hotels (`tourism=hotel`) within ``radius_km`` of a point.

        Uses Overpass ``around:`` filter for a true radial search — better
        than a bbox when the centre is a downtown coordinate (Bangkok,
        Madrid, etc.) because the bbox corners would pull in hotels
        outside the city's actual walkable footprint.

        Returns ``[]`` on Overpass error/timeout (the caller will surface
        an empty hotels list to the user rather than a fake number).
        """
        radius_m = int(radius_km * 1000)
        q = (
            f"[out:json][timeout:20];"
            f"node[\"tourism\"=\"hotel\"](around:{radius_m},{lat},{lon});"
            f"out {limit};"
        )
        try:
            data = await self._post(q)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Overpass search_hotels_near failed (%s, %s, %skm): %s",
                lat, lon, radius_km, e,
            )
            return []
        pois = self._parse_pois(data, category="hotel")
        logger.info(
            "Overpass search_hotels_near(%s, %s, %skm) found %d hotels",
            lat, lon, radius_km, len(pois),
        )
        return pois

    async def search_attractions_in_bbox(
        self, south: float, west: float, north: float, east: float, limit: int = 30,
    ) -> list[POI]:
        """Find tourist attractions (`tourism=attraction`) within bbox."""
        return await self._search_in_bbox(
            "attraction", south, west, north, east, limit,
        )


def build_overpass_client() -> OverpassClient:
    return OverpassClient()


__all__ = ["OverpassClient", "POI", "build_overpass_client"]

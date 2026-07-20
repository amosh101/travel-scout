"""OpenStreetMap Overpass API client — real HTTP wire for POI search.

Public API, no key needed. https://wiki.openstreetmap.org/wiki/Overpass_API
We use it for hotel/restaurant/attraction search as POI, in lieu of a paid
hotel API. POST requests (ToS); the `data` field is the Overpass-QL query.
"""
from __future__ import annotations

import asyncio
import logging
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
_HTTP_TIMEOUT = 30.0
_lock = asyncio.Lock()
# Be a good citizen: 2 req/sec across all mirrors.
_RATE_LIMIT_S = 0.6
_last_call = 0.0


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
        global _last_call
        async with _lock:
            now = asyncio.get_event_loop().time()
            wait = _RATE_LIMIT_S - (now - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call = asyncio.get_event_loop().time()
        last_err: Exception | None = None
        for mirror in _OVERPASS_MIRRORS:
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
                last_err = e
        raise last_err or RuntimeError("all Overpass mirrors failed")

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

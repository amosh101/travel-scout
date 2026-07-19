"""OSRM (Open Source Routing Machine) client — real HTTP wire for routing.

Public demo server, no key needed. https://project-osrm.org/docs/v5.24.0/api/
URL format: /route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}
NOTE: the demo server is a free public service with rate limits; for
production use, run your own OSRM or use a paid tier.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.clients.base import BaseClient

logger = logging.getLogger(__name__)

OSRM_BASE = "https://router.project-osrm.org"
_HTTP_TIMEOUT = 15.0
_RATE_LIMIT_S = 0.5  # 2 req/sec to be polite
_lock = asyncio.Lock()
_last_call = 0.0


@dataclass
class Route:
    distance_m: float
    duration_s: float
    geometry: dict | None  # GeoJSON LineString, if overview=full


class OSRMClient(BaseClient):
    source_key = "osrm"

    def is_configured(self) -> bool:
        return True

    async def route(
        self,
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
        profile: str = "driving",
        overview: str = "simplified",
    ) -> Route:
        global _last_call
        url = f"{OSRM_BASE}/route/v1/{profile}/{lon1},{lat1};{lon2},{lat2}"
        params = {"overview": overview, "alternatives": "false", "steps": "false"}
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
                    headers={"User-Agent": "TravelScout/2.0"},
                )
                r.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("OSRM route failed: %s", e)
                raise
        data = r.json()
        if data.get("code") != "Ok":
            raise RuntimeError(f"OSRM returned code {data.get('code')}: {data.get('message')}")
        routes = data.get("routes", [])
        if not routes:
            raise RuntimeError("OSRM returned no routes")
        chosen = routes[0]
        logger.info(
            "OSRM route %.1f km, %.0f min",
            chosen["distance"] / 1000,
            chosen["duration"] / 60,
        )
        return Route(
            distance_m=float(chosen["distance"]),
            duration_s=float(chosen["duration"]),
            geometry=chosen.get("geometry"),
        )


def build_osrm_client() -> OSRMClient:
    return OSRMClient()


__all__ = ["OSRMClient", "Route", "build_osrm_client"]

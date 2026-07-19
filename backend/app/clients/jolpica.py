"""Jolpica F1 client — real HTTP wire.

Public Ergast-compatible F1 endpoint, no API key needed.
Docs: https://github.com/jolpica/jolpica-f1 (Ergast-compatible)
Base: https://api.jolpi.ca/ergast/f1
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.clients.base import BaseClient, require_configured

logger = logging.getLogger(__name__)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
_HTTP_TIMEOUT = 15.0
_CONCURRENCY = 4
_sem = asyncio.Semaphore(_CONCURRENCY)


@dataclass
class JolpicaRace:
    source_event_id: str
    season: int
    round_number: int
    name: str
    circuit: str
    city: str
    country: str
    starts_at: datetime
    ends_at: datetime | None
    url: str | None


def _parse_dt(date_str: str | None, time_str: str | None) -> datetime | None:
    if not date_str:
        return None
    if time_str:
        return datetime.fromisoformat(f"{date_str}T{time_str}")
    return datetime.fromisoformat(f"{date_str}T00:00:00")


class JolpicaClient(BaseClient):
    source_key = "jolpica"

    def is_configured(self) -> bool:
        return True

    async def fetch_season(self, season: int) -> list[JolpicaRace]:
        require_configured(self)
        url = f"{JOLPICA_BASE}/{season}.json"
        async with _sem, httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                r = await client.get(url, headers={"User-Agent": "TravelScout/2.0"})
                r.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("Jolpica fetch_season(%d) failed: %s", season, e)
                raise
        data = r.json()
        races_raw = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        races: list[JolpicaRace] = []
        for r in races_raw:
            starts = _parse_dt(r.get("date"), r.get("time"))
            if starts is None:
                continue
            ends = _parse_dt(r.get("date"), None)
            circuit = r.get("Circuit", {})
            loc = circuit.get("Location", {})
            races.append(
                JolpicaRace(
                    source_event_id=f"jolpica:{season}:{r.get('round')}",
                    season=int(r.get("season", season)),
                    round_number=int(r.get("round", 0)),
                    name=r.get("raceName", ""),
                    circuit=circuit.get("circuitName", ""),
                    city=loc.get("locality", ""),
                    country=loc.get("country", ""),
                    starts_at=starts,
                    ends_at=ends,
                    url=r.get("url"),
                )
            )
        logger.info("Jolpica fetch_season(%d) returned %d races", season, len(races))
        return races

    async def next_race(self) -> JolpicaRace | None:
        from datetime import datetime as _dt, timezone

        season = _dt.now(timezone.utc).year
        races = await self.fetch_season(season)
        now = _dt.now(timezone.utc)
        for race in races:
            if race.starts_at >= now:
                return race
        return None


def build_jolpica_client() -> JolpicaClient:
    return JolpicaClient()


__all__ = ["JolpicaClient", "JolpicaRace", "build_jolpica_client"]

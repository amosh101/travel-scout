"""Nager.Date public holidays client — real HTTP wire.

Public API, no key needed. https://date.nager.at/api/v3
We use it for Mozambique (MZ) and surrounding SADC countries so the search
algorithm can warn about public-holiday price spikes.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.clients.base import BaseClient

logger = logging.getLogger(__name__)

NAGER_BASE = "https://date.nager.at/api/v3"
_HTTP_TIMEOUT = 15.0

# SADC countries we care about for travel-scout
SADC_COUNTRY_CODES = {
    "AO", # Angola
    "BW", # Botswana
    "CD", # DRC
    "SZ", # Eswatini
    "LS", # Lesotho
    "MG", # Madagascar
    "MW", # Malawi
    "MU", # Mauritius
    "MZ", # Mozambique
    "NA", # Namibia
    "SC", # Seychelles
    "ZA", # South Africa
    "TZ", # Tanzania
    "ZM", # Zambia
    "ZW", # Zimbabwe
}


@dataclass
class PublicHoliday:
    country_code: str
    date: str          # YYYY-MM-DD
    local_name: str
    english_name: str
    is_global: bool


class HolidaysClient(BaseClient):
    source_key = "holidays"

    def is_configured(self) -> bool:
        return True

    async def fetch_year(self, year: int, country_code: str) -> list[PublicHoliday]:
        url = f"{NAGER_BASE}/PublicHolidays/{year}/{country_code}"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                r = await client.get(url, headers={"User-Agent": "TravelScout/2.0"})
                r.raise_for_status()
            except httpx.HTTPError as e:
                logger.error("Holidays fetch_year(%d,%s) failed: %s", year, country_code, e)
                raise
        data = r.json()
        out: list[PublicHoliday] = []
        for h in data:
            out.append(
                PublicHoliday(
                    country_code=country_code,
                    date=h.get("date", ""),
                    local_name=h.get("localName", ""),
                    english_name=h.get("name", ""),
                    is_global=bool(h.get("global", False)),
                )
            )
        logger.info(
            "Holidays fetch_year(%d,%s) returned %d holidays",
            year, country_code, len(out),
        )
        return out

    async def fetch_year_sadc(self, year: int) -> dict[str, list[PublicHoliday]]:
        """Fetch holidays for all SADC countries we care about."""
        import asyncio

        async def _one(cc: str) -> tuple[str, list[PublicHoliday]]:
            try:
                return cc, await self.fetch_year(year, cc)
            except Exception as e:  # noqa: BLE001
                logger.warning("Holidays fetch_year(%d,%s) failed: %s", year, cc, e)
                return cc, []

        results = await asyncio.gather(*(_one(cc) for cc in SADC_COUNTRY_CODES))
        return dict(results)


def build_holidays_client() -> HolidaysClient:
    return HolidaysClient()


__all__ = [
    "HolidaysClient",
    "PublicHoliday",
    "SADC_COUNTRY_CODES",
    "build_holidays_client",
]

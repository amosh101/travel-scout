"""Kiwi.com (Tequila) flight search client — real HTTP wire.

Requires ``KIWI_API_KEY`` in env. If not set, ``is_configured()`` returns
False and the search router can skip this source without crashing.

Tequila API docs: https://tequila.kiwi.com/portal/docs
Base: https://api.tequila.kiwi.com/v2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx

from app.clients.base import BaseClient, require_configured
from app.config import get_settings

logger = logging.getLogger(__name__)

TEQUILA_BASE = "https://api.tequila.kiwi.com/v2"
_HTTP_TIMEOUT = 15.0


@dataclass
class KiwiFlightOffer:
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    price_cents: int
    currency: str
    airline: str | None
    deep_link: str | None


class KiwiClient(BaseClient):
    source_key = "kiwi"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search_flights(
        self,
        *,
        origin: str,
        destination: str,
        depart: date,
        return_date: date | None = None,
        currency: str = "USD",
        limit: int = 10,
    ) -> list[KiwiFlightOffer]:
        """Search for flights. Returns a sorted list (cheapest first).

        Empty list if the API returns no flights or the call fails. The
        caller is expected to surface "flights unavailable" to the user,
        not a hard error — flight search is best-effort enrichment, not
        a hard product requirement.
        """
        require_configured(self)
        params: dict[str, str | int] = {
            "fly_from": origin.upper(),
            "fly_to": destination.upper(),
            "date_from": depart.isoformat(),
            "date_to": depart.isoformat(),
            "curr": currency.upper(),
            "limit": limit,
            "one_for_city": 1,
        }
        if return_date is not None:
            params["return_from"] = return_date.isoformat()
            params["return_to"] = return_date.isoformat()
        headers: dict[str, str] = {"apikey": self._api_key or ""}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                r = await client.get(
                    f"{TEQUILA_BASE}/search", params=params, headers=headers
                )
                r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Kiwi search failed: %s", e)
            return []
        data = r.json() or {}
        offers: list[KiwiFlightOffer] = []
        for item in data.get("data", []) or []:
            try:
                price = int(round(float(item.get("price", 0)) * 100))
            except (TypeError, ValueError):
                continue
            depart_dt = item.get("local_departure") or item.get("utc_departure")
            try:
                from datetime import datetime as _dt
                depart_date = _dt.fromisoformat(
                    depart_dt.split("T")[0]
                ).date() if depart_dt else depart
            except (ValueError, AttributeError):
                depart_date = depart
            offers.append(
                KiwiFlightOffer(
                    origin=item.get("flyFrom", origin).upper(),
                    destination=item.get("flyTo", destination).upper(),
                    depart_date=depart_date,
                    return_date=return_date,
                    price_cents=price,
                    currency=currency.upper(),
                    airline=item.get("airlines", [None])[0] if item.get("airlines") else None,
                    deep_link=item.get("deep_link"),
                )
            )
        offers.sort(key=lambda o: o.price_cents)
        logger.info("Kiwi search %s->%s on %s returned %d offers",
                     origin, destination, depart, len(offers))
        return offers


def build_kiwi_client() -> KiwiClient:
    return KiwiClient(api_key=get_settings().kiwi_api_key or None)


__all__ = ["KiwiClient", "KiwiFlightOffer", "build_kiwi_client"]

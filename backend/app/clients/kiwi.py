"""Kiwi.com flight search client.

Stub interface only — the real HTTP wiring lands in the user-journey card.
For foundation we ship the protocol + factory + not-configured guard so the
rest of the app can be built against the shape without leaking keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.clients.base import BaseClient, require_configured
from app.config import get_settings


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
    ) -> list[KiwiFlightOffer]:
        require_configured(self)
        # Real HTTP call lands in t3_user_journey.
        raise NotImplementedError("wiring in t3_user_journey")


def build_kiwi_client() -> KiwiClient:
    return KiwiClient(api_key=get_settings().kiwi_api_key or None)


__all__ = ["KiwiClient", "KiwiFlightOffer", "build_kiwi_client"]
"""Jolpica F1 client.

Stub interface — real HTTP wiring lands in t3_user_journey.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.clients.base import BaseClient, require_configured
from app.config import get_settings


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


class JolpicaClient(BaseClient):
    source_key = "jolpica"

    def __init__(self, api_key: str | None = None) -> None:
        # Jolpica's public F1 endpoint is unauthenticated; api_key is optional.
        self._api_key = api_key

    def is_configured(self) -> bool:
        # Always configured — public API.
        return True

    async def fetch_season(self, season: int) -> list[JolpicaRace]:
        require_configured(self)
        raise NotImplementedError("wiring in t3_user_journey")


def build_jolpica_client() -> JolpicaClient:
    return JolpicaClient(api_key=get_settings().jolpica_api_key or None)


__all__ = ["JolpicaClient", "JolpicaRace", "build_jolpica_client"]
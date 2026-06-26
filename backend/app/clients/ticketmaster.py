"""Ticketmaster events client.

Stub interface — real HTTP wiring lands in t3_user_journey.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.clients.base import BaseClient, require_configured
from app.config import get_settings


@dataclass
class TicketmasterEvent:
    source_event_id: str
    title: str
    category: str | None
    starts_at: datetime
    ends_at: datetime | None
    url: str | None
    venue_city: str | None
    venue_country: str | None


class TicketmasterClient(BaseClient):
    source_key = "ticketmaster"

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search_events(
        self,
        *,
        city: str | None = None,
        country: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[TicketmasterEvent]:
        require_configured(self)
        raise NotImplementedError("wiring in t3_user_journey")


def build_ticketmaster_client() -> TicketmasterClient:
    return TicketmasterClient(api_key=get_settings().ticketmaster_api_key or None)


__all__ = ["TicketmasterClient", "TicketmasterEvent", "build_ticketmaster_client"]
"""Ticketmaster Discovery events client — real HTTP wire.

Requires ``TICKETMASTER_API_KEY`` in env. If not set, ``is_configured()``
returns False and the search router can skip this source without crashing.

Discovery API docs: https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.clients.base import BaseClient, require_configured
from app.config import get_settings

logger = logging.getLogger(__name__)

TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2"
_HTTP_TIMEOUT = 15.0


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
        keyword: str | None = None,
        size: int = 20,
    ) -> list[TicketmasterEvent]:
        """Search events. Returns [] on any failure (best-effort enrichment)."""
        require_configured(self)
        params: dict[str, str | int] = {
            "apikey": self._api_key or "",
            "size": size,
            "sort": "date,asc",
        }
        if city:
            params["city"] = city
        if country:
            params["countryCode"] = country.upper()
        if start_date:
            params["startDateTime"] = start_date.isoformat() + "Z"
        if end_date:
            params["endDateTime"] = end_date.isoformat() + "Z"
        if keyword:
            params["keyword"] = keyword
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                r = await client.get(
                    f"{TICKETMASTER_BASE}/events.json", params=params
                )
                r.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Ticketmaster search failed: %s", e)
            return []
        data = r.json() or {}
        events: list[TicketmasterEvent] = []
        for ev in data.get("_embedded", {}).get("events", []) or []:
            try:
                starts_str = ev.get("dates", {}).get("start", {}).get("dateTime")
                if not starts_str:
                    continue
                starts = datetime.fromisoformat(starts_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            end_str = ev.get("dates", {}).get("end", {}).get("dateTime")
            ends_at: datetime | None = None
            if end_str:
                try:
                    ends_at = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                except ValueError:
                    ends_at = None
            venues = (ev.get("_embedded", {}) or {}).get("venues", []) or []
            venue = venues[0] if venues else {}
            city_name = (venue.get("city") or {}).get("name")
            country_code = (venue.get("country") or {}).get("countryCode")
            # Classify: try to pull a top-level category / segment.
            classifications = ev.get("classifications", []) or []
            cat: str | None = None
            if classifications:
                seg = (classifications[0].get("segment") or {}).get("name")
                if seg:
                    cat = seg
            events.append(
                TicketmasterEvent(
                    source_event_id=ev.get("id", ""),
                    title=ev.get("name", ""),
                    category=cat,
                    starts_at=starts,
                    ends_at=ends_at,
                    url=ev.get("url"),
                    venue_city=city_name,
                    venue_country=country_code,
                )
            )
        logger.info("Ticketmaster search returned %d events", len(events))
        return events


def build_ticketmaster_client() -> TicketmasterClient:
    return TicketmasterClient(api_key=get_settings().ticketmaster_api_key or None)


__all__ = ["TicketmasterEvent", "TicketmasterClient", "build_ticketmaster_client"]

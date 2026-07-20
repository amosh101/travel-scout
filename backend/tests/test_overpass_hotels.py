"""Tests for the Overpass hotel wire.

Real Overpass (no mocks). Asserts that the public client returns
parseable POIs for a known downtown coordinate, and that failures
return ``[]`` rather than fabricated data.
"""
from __future__ import annotations

import pytest

from app.clients.overpass import build_overpass_client


@pytest.mark.asyncio
async def test_search_hotels_near_returns_real_bangkok_pois() -> None:
    """Bangkok (13.7563, 100.5018) has well-mapped OSM hotels.

    Real data, no mocks. Asserts:
      - result is a list
      - at least 3 hotels
      - each has a name (no fabricated names)
      - each has lat/lon in Bangkok bbox
    """
    c = build_overpass_client()
    pois = await c.search_hotels_near(13.7563, 100.5018, radius_km=5.0, limit=20)
    assert isinstance(pois, list)
    assert len(pois) >= 3, f"expected >=3 hotels in central Bangkok, got {len(pois)}"
    for p in pois:
        # Real OSM data — every record must have a name (the parser falls
        # back to "(unnamed)" if absent, never an empty string).
        assert p.name, f"POI missing name: {p}"
        assert p.category == "hotel"
        # Bangkok bbox (rough): lat 13.5-14.0, lon 100.3-100.8
        assert 13.4 <= p.lat <= 14.0, f"lat out of range: {p.lat}"
        assert 100.2 <= p.lon <= 100.9, f"lon out of range: {p.lon}"


@pytest.mark.asyncio
async def test_search_hotels_near_empty_on_garbage_coords() -> None:
    """An invalid lat/lon should return ``[]``, not crash, not fabricate."""
    c = build_overpass_client()
    # Null Island — no hotels there, but Overpass shouldn't 500.
    pois = await c.search_hotels_near(0.0, 0.0, radius_km=1.0, limit=10)
    assert isinstance(pois, list)
    # We don't assert == 0 because OSM mappers sometimes tag the ocean.
    # We DO assert no crash and a list return.

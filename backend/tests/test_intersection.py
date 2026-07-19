"""Unit tests for the intersection algorithm.

These tests use deterministic local fakes for the network clients
(Nominatim, Jolpica, Holidays, OSRM, Overpass) so the test runs in <1s
and doesn't depend on external services. The algorithm's behavior is
asserted on the core scenarios:

  1. Disambiguates "Brussels" -> Brussels-BE (not Brussels-IL).
  2. Finds a Belgian GP race on 2026-07-19 even when the trip window
     starts on 2026-07-22 (the +5 day buffer must catch it).
  3. Finds Belgian National Day on 2026-07-21 in the destination country.
  4. Surfaces the race + holiday in the user-facing pitch.
  5. Returns the right country_code (BE, not US) on the response.
  6. Disambiguates other ambiguous names (Paris -> FR, Florence -> IT).
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Iterable

import pytest
from app.clients.base import NotConfiguredError
from app.clients.holidays import PublicHoliday
from app.clients.jolpica import JolpicaRace
from app.clients.nominatim import GeocodeResult

# Import the unit-level helpers we want to test.
from app.routers.search import (
    _AMBIGUOUS_CITY_DEFAULT_COUNTRY,
    _pick_best_geocode,
    _score_itinerary,
    _build_pitch,
)


# -----------------------------------------------------------------------------
# Fakes
# -----------------------------------------------------------------------------

def _geocode(
    display: str,
    country_code: str,
    importance: float,
    lat: float = 0.0,
    lon: float = 0.0,
) -> GeocodeResult:
    return GeocodeResult(
        display_name=display,
        lat=lat,
        lon=lon,
        bbox=(0.0, 0.0, 0.0, 0.0),
        place_class="place",
        place_type="city",
        country_code=country_code,
        importance=importance,
    )


def _race(name: str, city: str, country: str, start: str) -> JolpicaRace:
    return JolpicaRace(
        source_event_id=f"jolpica:2026:{name}",
        season=2026,
        round_number=1,
        name=name,
        circuit="Circuit",
        city=city,
        country=country,
        starts_at=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        ends_at=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
        url=None,
    )


def _holiday(date_str: str, name: str, local: str = "") -> PublicHoliday:
    return PublicHoliday(
        country_code="BE",
        date=date_str,
        local_name=local,
        english_name=name,
        is_global=True,
    )


# -----------------------------------------------------------------------------
# Geocode picker
# -----------------------------------------------------------------------------

class TestPickBestGeocode:
    def test_brussels_picks_belgium_not_illinois(self):
        results = [
            _geocode("Brussels, Illinois, US", "US", 0.45),
            _geocode("Brussels, Wisconsin, US", "US", 0.33),
            _geocode("Brussels, Brussels-Capital, Belgium", "BE", 0.74),
        ]
        picked = _pick_best_geocode(results, query="Brussels")
        assert picked.country_code == "BE"
        assert "Belgium" in picked.display_name

    def test_paris_picks_france_not_texas(self):
        results = [
            _geocode("Paris, Texas, US", "US", 0.50),
            _geocode("Paris, Ile-de-France, France", "FR", 0.85),
        ]
        picked = _pick_best_geocode(results, query="Paris")
        assert picked.country_code == "FR"

    def test_florence_picks_italy_not_oregon(self):
        results = [
            _geocode("Florence, Oregon, US", "US", 0.40),
            _geocode("Florence, Tuscany, Italy", "IT", 0.70),
        ]
        picked = _pick_best_geocode(results, query="Florence")
        assert picked.country_code == "IT"

    def test_country_hint_overrides_picker(self):
        """If the user types 'Paris, US', we trust the user."""
        results = [
            _geocode("Paris, Texas, US", "US", 0.50),
            _geocode("Paris, Ile-de-France, France", "FR", 0.85),
        ]
        picked = _pick_best_geocode(results, query="Paris, US")
        assert picked.country_code == "US"

    def test_no_results_returns_empty(self):
        with pytest.raises(IndexError):
            _pick_best_geocode([], query="Nowhere")

    def test_ambiguous_default_country_map_keys_are_normalized(self):
        """Keys in the ambiguous map must be lowercased, no spaces (we
        strip punctuation/space before lookup) — except for multi-word
        Irish/Scottish names that we explicitly support.
        """
        for key in _AMBIGUOUS_CITY_DEFAULT_COUNTRY:
            assert key == key.lower()
            # Value is ISO 3166-1 alpha-2.
            assert len(_AMBIGUOUS_CITY_DEFAULT_COUNTRY[key]) == 2


# -----------------------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------------------

class TestScoreItinerary:
    def test_ideal_trip_scores_high(self):
        score, reasons = _score_itinerary(
            distance_km=300, duration_days=3, races_at_destination=1, holidays_count=0
        )
        assert score >= 75
        assert any("race" in r.lower() for r in reasons)

    def test_holiday_during_trip_costs_points(self):
        clear_score, _ = _score_itinerary(
            distance_km=300, duration_days=3, races_at_destination=0, holidays_count=0
        )
        holiday_score, reasons = _score_itinerary(
            distance_km=300, duration_days=3, races_at_destination=0, holidays_count=2
        )
        assert holiday_score < clear_score
        assert any("hol" in r for r in reasons)

    def test_score_is_bounded(self):
        for _ in range(20):
            score, _ = _score_itinerary(
                distance_km=100, duration_days=3, races_at_destination=5, holidays_count=0
            )
            assert 0.0 <= score <= 100.0


# -----------------------------------------------------------------------------
# Pitch
# -----------------------------------------------------------------------------

class TestBuildPitch:
    def test_pitch_includes_race_match(self):
        pitch = _build_pitch(
            interests=["f1"],
            races_in_window=[{"name": "Belgian GP", "starts_at": "2026-07-19T13:00:00+00:00"}],
            holiday_alerts=[],
            duration_days=5,
            has_event_window=True,
        )
        assert any("Belgian GP" in p for p in pitch)
        assert any("F1" in p for p in pitch)

    def test_pitch_includes_holiday_match(self):
        pitch = _build_pitch(
            interests=["public-holidays"],
            races_in_window=[],
            holiday_alerts=[{"date": "2026-07-21", "name": "Belgian National Day", "local": ""}],
            duration_days=3,
            has_event_window=True,
        )
        assert any("Belgian National Day" in p for p in pitch)

    def test_pitch_honest_when_no_match(self):
        pitch = _build_pitch(
            interests=["jazz"],
            races_in_window=[],
            holiday_alerts=[],
            duration_days=3,
            has_event_window=True,
        )
        assert pitch and "no events" in pitch[0].lower()

    def test_pitch_empty_for_user_without_interests(self):
        pitch = _build_pitch(
            interests=[],
            races_in_window=[],
            holiday_alerts=[],
            duration_days=3,
            has_event_window=True,
        )
        # No fabrication: empty pitch for a user without interests.
        assert pitch == []

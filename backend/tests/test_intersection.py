"""Unit tests for the intersection algorithm.

The intersection algorithm's pure functions (scoring, pitch) are tested
here. The location resolution (city/country/alias disambiguation) is
now handled by ReferenceService and tested in test_refdata.py with a
real DB session — no mocks.

These tests assert:
  - The scoring function's bounds and weighting
  - The pitch function's user-facing honesty (empty for users without
    interests; "no events" message when interests don't match)
  - That the constants used by the search router are real named
    constants, not magic numbers
"""
from __future__ import annotations

import pytest
from app.routers.search import (
    EVENT_WINDOW_BUFFER_DAYS,
    RACE_AT_DESTINATION_RADIUS_KM,
    MIN_REFDATA_CONFIDENCE,
    _score_itinerary,
    _build_pitch,
)


# -----------------------------------------------------------------------------
# Constants are real named constants, not magic numbers
# -----------------------------------------------------------------------------

class TestConstants:
    def test_race_radius_is_a_real_distance(self):
        # 200 km: Spa→Brussels, Monza→Milan, Silverstone→London all
        # fit; a transcontinental leg doesn't.
        assert 50.0 <= RACE_AT_DESTINATION_RADIUS_KM <= 500.0

    def test_event_buffer_is_a_real_number_of_days(self):
        # ±5 days covers F1 Fri–Sun plus 1–2 day flights.
        assert 1 <= EVENT_WINDOW_BUFFER_DAYS <= 14

    def test_min_confidence_is_a_real_threshold(self):
        assert 0.0 < MIN_REFDATA_CONFIDENCE <= 1.0


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
        assert pitch == []

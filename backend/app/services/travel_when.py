"""Date-window semantics for the user's profile.

The user picks a "when" (now / month / quarter / year / specific). The
front-end uses the same labels. The discover router clamps the F1
candidate pool + holiday fetch to this window so we never surface an
event outside what the user actually asked for.

A future "upcoming events" tab can scan beyond this window; today the
profile window is the only window. See PRD §3.2.

The 180-day hard cap (``SPECIFIC``) is the maximum lookahead regardless
of which preset the user picks — keeps the intersection algorithm from
being asked to scan too much.
"""
from __future__ import annotations

from datetime import date, timedelta
from enum import Enum


class TravelWhen(str, Enum):
    """When the user wants to travel. Maps to a fixed date window."""

    NOW = "now"          # next 14 days
    MONTH = "month"      # next 30 days
    QUARTER = "quarter"  # next 90 days
    YEAR = "year"        # next 180 days
    SPECIFIC = "specific"  # user picked date_from / date_to


# Lookup days for each preset. SPECIFIC is bounded by MAX_LOOKAHEAD_DAYS
# but the user-supplied window itself is the truth.
_LOOKAHEAD_DAYS: dict[TravelWhen, int] = {
    TravelWhen.NOW: 14,
    TravelWhen.MONTH: 30,
    TravelWhen.QUARTER: 90,
    TravelWhen.YEAR: 180,
    TravelWhen.SPECIFIC: 180,
}

# Single source of truth for the maximum lookahead window. Used by:
# - the intake handler to reject SPECIFIC windows beyond this
# - the discover router as the cap for the YEAR preset
MAX_LOOKAHEAD_DAYS = 180


def label(when: TravelWhen) -> str:
    """Human label, e.g. ``"next 3 months"``. Used on the result page."""
    return {
        TravelWhen.NOW: "next 2 weeks",
        TravelWhen.MONTH: "next month",
        TravelWhen.QUARTER: "next 3 months",
        TravelWhen.YEAR: "next 6 months",
        TravelWhen.SPECIFIC: "the dates you picked",
    }[when]


def window_for(when: TravelWhen, today: date | None = None) -> tuple[date, date]:
    """Return ``(date_from, date_to)`` for a preset, relative to ``today``."""
    t = today or date.today()
    days = _LOOKAHEAD_DAYS[when]
    return (t, t + timedelta(days=days))


def is_within_window(target: date, win_from: date, win_to: date) -> bool:
    """True if ``target`` is on or inside the inclusive window."""
    return win_from <= target <= win_to

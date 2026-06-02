"""
Enhanced Flight Scraper with Browser Integration

Integrates:
1. Browser-based scraping (browser_flight_scraper.py)
2. Legacy caching/proxy services (if available)
3. Honest fallback (no mock data)
"""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from .flight_scraper import search_flights, get_best_flight, FlightOffer

# Try to import enhanced features (may not be available)
try:
    from .cache import cache_service
    from .scraping_utils import get_stealth_session, rate_limiter
    HAS_ENHANCED = True
except ImportError:
    HAS_ENHANCED = False


# Re-export the main functions and FlightOffer
__all__ = ['search_flights', 'get_best_flight', 'FlightOffer']


# Legacy API compatibility
async def search_kiwi_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """Legacy Kiwi API search - redirects to browser scraper."""
    # Use the main search which includes browser scraping
    return await search_flights(origin, destination, date_from, date_to, max_price)


async def search_google_flights_scrape(
    origin: str,
    destination: str,
    date_from: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """Legacy Google Flights search - redirects to browser scraper."""
    date_to = date_from + timedelta(days=7)
    return await search_flights(origin, destination, date_from, date_to, max_price)


# Backwards compatibility
def get_sample_flights(*args, **kwargs) -> List[FlightOffer]:
    """Deprecated: Returns empty list (no mock data)."""
    return []


FlightOfferEnhanced = FlightOffer

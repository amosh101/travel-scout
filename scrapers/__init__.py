"""
Browser-based Flight Scraper Module

Provides real flight price scraping from multiple sources:
- Kayak (HTML extraction)
- Skyscanner (HTML extraction)
- Google Flights (HTML extraction)
- Aviasales (search link generation)

Usage:
    python browser_flight_scraper.py --origin MPM --destination LHR --depart 2026-08-15

Note: Flight sites have anti-bot protection. Prices may need verification.
"""

from .browser_flight_scraper import FlightScraper, FlightOffer

__all__ = ['FlightScraper', 'FlightOffer']

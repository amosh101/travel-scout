"""
Flight Scraper - Honest Implementation with Browser Integration

Integrates:
1. Browser-based scraper (real web scraping)
2. Neural Search (if indexed)
3. Returns empty with explanation if all fail

NO MOCK DATA. EVER.
"""

import asyncio
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional


@dataclass
class FlightOffer:
    """Real flight offer - verified from actual source."""
    origin: str
    destination: str
    airline: str
    price: float
    currency: str
    depart_date: date
    return_date: Optional[date]
    duration_minutes: int
    stops: int
    booking_link: str
    data_source: str  # "neural", "api", "browser", "none"
    is_verified: bool  # True if from live source, False if cached/indexed


def _convert_browser_offer(offer_data: dict) -> FlightOffer:
    """Convert browser scraper output to FlightOffer."""
    return FlightOffer(
        origin=offer_data.get('origin', ''),
        destination=offer_data.get('destination', ''),
        airline=offer_data.get('airline', 'Unknown'),
        price=float(offer_data.get('price', 0)),
        currency=offer_data.get('currency', 'USD'),
        depart_date=date.fromisoformat(offer_data['depart_date']) if offer_data.get('depart_date') else date.today(),
        return_date=date.fromisoformat(offer_data['return_date']) if offer_data.get('return_date') else None,
        duration_minutes=offer_data.get('duration_minutes', 0),
        stops=offer_data.get('stops', 0),
        booking_link=offer_data.get('booking_link', ''),
        data_source=offer_data.get('source', 'browser'),
        is_verified=offer_data.get('confidence') in ['high', 'medium']
    )


async def search_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search for flights using multiple real data sources.
    
    Priority:
    1. Browser-based scraper (calls browser_flight_scraper.py)
    2. Neural search (if flight data indexed)
    3. Return empty list if all fail
    """
    offers = []
    
    # 1. Try browser scraper
    browser_offers = await _search_with_browser(origin, destination, date_from, date_to, max_price)
    offers.extend(browser_offers)
    
    # 2. Try neural search (if available)
    if not offers:
        neural_offers = await _search_neural(origin, destination, date_from, date_to, max_price)
        offers.extend(neural_offers)
    
    return offers


async def _search_with_browser(
    origin: str,
    destination: str,
    depart_date: date,
    return_date: Optional[date],
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Call the browser-based flight scraper.
    """
    offers = []
    
    try:
        # Find the browser scraper script
        script_path = Path(__file__).parent.parent.parent.parent / 'scrapers' / 'browser_flight_scraper.py'
        
        if not script_path.exists():
            # Try alternative path
            script_path = Path('/home/ubuntu/.openclaw/workspace/projects/travel-scout/scrapers/browser_flight_scraper.py')
        
        if not script_path.exists():
            return []
        
        # Build command
        cmd = [
            sys.executable,
            str(script_path),
            '--origin', origin,
            '--destination', destination,
            '--depart', depart_date.isoformat(),
        ]
        
        if return_date:
            cmd.extend(['--return', return_date.isoformat()])
        
        cmd.extend(['--max-results', '10'])
        
        # Run scraper with timeout
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return []
        
        # Parse JSON output
        output = stdout.decode('utf-8')
        
        # Find JSON section - look for the array starting with [
        json_match = re.search(r'(\[.*\])', output, re.DOTALL)
        if json_match:
            json_section = json_match.group(1)
            
            try:
                offers_data = json.loads(json_section)
                
                for offer_data in offers_data:
                    offer = _convert_browser_offer(offer_data)
                    
                    # Apply max_price filter
                    if max_price and offer.price > max_price:
                        continue
                    
                    offers.append(offer)
                
            except json.JSONDecodeError as e:
                print(f"JSON parse error: {e}")
        
    except Exception as e:
        # Log error but don't fail - return empty list
        print(f"Browser scraper error: {e}")
    
    return offers


async def _search_neural(
    origin: str,
    destination: str,
    date_from: date,
    date_to: Optional[date],
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search neural database for flight data.
    TODO: Implement if/when flight data is indexed.
    """
    # Neural search not implemented yet for flights
    return []


async def get_best_flight(
    origin: str,
    destination: str,
    date_from: date,
    date_to: Optional[date] = None,
    max_price: Optional[float] = None
) -> Optional[FlightOffer]:
    """Get best flight - returns None if no real data available."""
    flights = await search_flights(origin, destination, date_from, date_to, max_price)
    
    if not flights:
        return None
    
    # Sort by price (cheapest first)
    flights.sort(key=lambda x: x.price if x.price > 0 else float('inf'))
    
    return flights[0]


# Backwards compatibility with flight_scraper_enhanced.py
FlightOfferEnhanced = FlightOffer


__all__ = ['search_flights', 'get_best_flight', 'FlightOffer']

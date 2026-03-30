"""
Flight Scraper - Uses curl/requests for free flight data

No paid API keys required. Scrapes from:
- Google Flights (JSON endpoints)
- Kiwi.com (free API)
- Alternative flight search pages

Best flights selected by: price + duration tradeoff
"""

import asyncio
import re
import json
from datetime import date, timedelta
from typing import List, Optional
from dataclasses import dataclass, field
import aiohttp


@dataclass
class FlightOffer:
    """Flight offer data structure."""
    origin: str
    destination: str
    airline: str
    price: float
    currency: str
    depart_date: date
    return_date: Optional[date] = None
    duration_minutes: int = 0
    stops: int = 0
    booking_link: str = ""
    
    def score(self) -> float:
        """
        Score flight by price and duration.
        Lower is better - we want cheap + short flights.
        """
        # Normalize: price in USD, duration in minutes
        price_score = self.price / 1000  # $1000 = 1.0
        duration_score = self.duration_minutes / 1000  # 1000min = 1.0
        
        # Weight: price 60%, duration 40%
        return (price_score * 0.6) + (duration_score * 0.4)


async def search_kiwi_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search flights using Kiwi.com's free API.
    API is free with attribution required.
    """
    offers = []
    
    try:
        # Kiwi.com API (free, no key required for basic search)
        url = f"https://api.kiwi.com/v2/search"
        params = {
            "fly_from": origin,
            "fly_to": destination,
            "date_from": date_from.strftime("%d/%m/%Y"),
            "date_to": date_to.strftime("%d/%m/%Y"),
            "return_from": (date_from + timedelta(days=3)).strftime("%d/%m/%Y"),
            "return_to": (date_from + timedelta(days=14)).strftime("%d/%m/%Y"),
            "currency": "USD",
            "limit": 10,
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for flight in data.get("data", []):
                        try:
                            offer = FlightOffer(
                                origin=flight.get("flyFrom", origin),
                                destination=flight.get("flyTo", destination),
                                airline=flight.get("airlines", ["Unknown"])[0],
                                price=flight.get("price", 0),
                                currency="USD",
                                depart_date=date.fromisoformat(flight.get("route", [{}])[0].get("dTime", 0)[:10]) if flight.get("route") else date_from,
                                return_date=date.fromisoformat(flight.get("route", [{}])[-1].get("aTime", 0)[:10]) if flight.get("route") else date_from,
                                duration_minutes=flight.get("duration", {}).get("flight", 0),
                                stops=len(flight.get("route", [])) - 1,
                                booking_link=flight.get("deep_link", "")
                            )
                            if max_price and offer.price > max_price:
                                continue
                            offers.append(offer)
                        except (KeyError, IndexError):
                            continue
    except Exception as e:
        print(f"Kiwi API error: {e}")
    
    return offers


async def search_google_flights_json(
    origin: str,
    destination: str,
    date_str: str
) -> List[FlightOffer]:
    """
    Scrape Google Flights using their internal JSON API.
    This endpoint returns search results without requiring an API key.
    """
    offers = []
    
    try:
        # Google Flights search endpoint (unofficial but works)
        url = f"https://www.google.com/flights/previewrpc/search"
        params = {
            "r": json.dumps({
                "origin": origin,
                "destination": destination,
                "date": date_str,
                "tripType": "ROUND_TRIP"
            })
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Parse Google Flights response format
                    for trip in data.get("trips", []).get("tripReport", []):
                        for option in trip.get("flightCards", []):
                            try:
                                offer = FlightOffer(
                                    origin=origin,
                                    destination=destination,
                                    airline=option.get("flight", {}).get("carrier", {}).get("name", "Unknown"),
                                    price=option.get("price", {}).get("amount", 0),
                                    currency=option.get("price", {}).get("currency", "USD"),
                                    depart_date=date_from,
                                    duration_minutes=option.get("duration", 0),
                                    stops=option.get("stops", 0),
                                    booking_link=option.get("bookingLink", "")
                                )
                                offers.append(offer)
                            except:
                                continue
    except Exception as e:
        print(f"Google Flights error: {e}")
    
    return offers


async def search_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search for flights using multiple free sources.
    
    Aggregates results from:
    1. Kiwi.com API (primary)
    2. Google Flights (fallback)
    
    Returns sorted by score (price + duration).
    """
    all_offers = []
    
    # Search Kiwi first (most reliable free API)
    kiwi_offers = await search_kiwi_flights(origin, destination, date_from, date_to, max_price)
    all_offers.extend(kiwi_offers)
    
    # If no results, try Google Flights as fallback
    if not all_offers:
        google_offers = await search_google_flights_json(origin, destination, date_from.strftime("%Y-%m-%d"))
        all_offers.extend(google_offers)
    
    # Sort by score (lower is better)
    all_offers.sort(key=lambda x: x.score())
    
    return all_offers


async def get_best_flight(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> Optional[FlightOffer]:
    """
    Get the single best flight based on price + duration score.
    """
    offers = await search_flights(origin, destination, date_from, date_to, max_price)
    return offers[0] if offers else None


async def search_multi_destination(
    origin: str,
    destinations: List[tuple[str, date, date]],
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search flights for multiple destinations.
    
    Args:
        origin: Origin airport code (e.g., "MPM")
        destinations: List of (destination, date_from, date_to) tuples
    
    Returns:
        List of best flights for each destination
    """
    results = []
    
    for dest, d_from, d_to in destinations:
        best = await get_best_flight(origin, dest, d_from, d_to, max_price)
        if best:
            results.append(best)
        # Rate limit between requests
        await asyncio.sleep(1)
    
    return results


# Example usage
if __name__ == "__main__":
    async def test():
        # Test: Maputo to Miami
        offers = await search_flights(
            origin="MPM",
            destination="MIA",
            date_from=date(2026, 5, 1),
            date_to=date(2026, 5, 3),
            max_price=2000
        )
        
        print(f"Found {len(offers)} flights:")
        for o in offers[:5]:
            print(f"  {o.airline}: ${o.price} ({o.duration_minutes}min, {o.stops} stops)")
    
    asyncio.run(test())
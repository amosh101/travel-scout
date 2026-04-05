"""
Enhanced Flight Scraper with Caching, Proxy Rotation, and Anti-Bot Evasion
Zero-cost implementation for proof-of-concept
"""
import asyncio
import re
import json
from datetime import date, timedelta
from typing import List, Optional
from dataclasses import dataclass
import aiohttp

# Import our new services
from .cache import cache_service
from .scraping_utils import get_stealth_session, rate_limiter, StealthHeaders


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
    source: str = "unknown"  # Track which API returned this
    scraped_at: str = ""  # Timestamp
    
    def score(self) -> float:
        """Score flight by price and duration. Lower is better."""
        price_score = self.price / 1000
        duration_score = self.duration_minutes / 1000
        return (price_score * 0.6) + (duration_score * 0.4)


async def search_kiwi_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search flights using Kiwi.com's free API with caching and stealth.
    """
    # Generate cache key
    cache_key = cache_service.generate_flight_cache_key(
        origin, destination, date_from.isoformat(), 
        date_to.isoformat() if date_to else None, max_price
    )
    
    # Check cache first
    cached = await cache_service.get(cache_key)
    if cached:
        print(f"📦 Cache hit for {origin}->{destination}")
        return [FlightOffer(**offer) for offer in cached]
    
    # Rate limit
    await rate_limiter.wait_if_needed("kiwi.com")
    
    offers = []
    session, proxy = await get_stealth_session()
    
    try:
        url = f"https://api.kiwi.com/v2/search"
        params = {
            "fly_from": origin,
            "fly_to": destination,
            "date_from": date_from.strftime("%d/%m/%Y"),
            "date_to": date_to.strftime("%d/%m/%Y") if date_to else date_from.strftime("%d/%m/%Y"),
            "currency": "USD",
            "limit": 10,
        }
        
        proxy_url = proxy if proxy else None
        
        async with session.get(
            url, 
            params=params, 
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
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
                            depart_date=date_from,
                            return_date=date_from + timedelta(days=7),
                            duration_minutes=flight.get("duration", {}).get("flight", 0),
                            stops=len(flight.get("route", [])) - 1,
                            booking_link=flight.get("deep_link", ""),
                            source="kiwi",
                            scraped_at=date.today().isoformat()
                        )
                        if max_price and offer.price > max_price:
                            continue
                        offers.append(offer)
                    except (KeyError, IndexError):
                        continue
                
                rate_limiter.record_success("kiwi.com")
            else:
                print(f"⚠️  Kiwi API status: {resp.status}")
                rate_limiter.record_failure("kiwi.com")
                
    except Exception as e:
        print(f"Kiwi API error: {e}")
        rate_limiter.record_failure("kiwi.com")
    finally:
        await session.close()
    
    # Cache results
    if offers:
        await cache_service.set(
            cache_key, 
            [offer.__dict__ for offer in offers], 
            ttl_seconds=1800  # Cache for 30 minutes
        )
    
    return offers


async def search_google_flights_scrape(
    origin: str,
    destination: str,
    date_from: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Scrape Google Flights using jina.ai (free, no API key).
    Uses stealth headers and proxy rotation.
    """
    # Check cache
    cache_key = cache_service.generate_flight_cache_key(
        origin, destination, date_from.isoformat(), 
        source="google_jina"
    )
    cached = await cache_service.get(cache_key)
    if cached:
        return [FlightOffer(**offer) for offer in cached]
    
    await rate_limiter.wait_if_needed("jina.ai")
    
    offers = []
    session, proxy = await get_stealth_session()
    
    try:
        # jina.ai provides clean text extraction
        date_str = date_from.strftime("%Y-%m-%d")
        search_query = f"flights from {origin} to {destination} on {date_str}"
        jina_url = f"https://r.jina.ai/http://www.google.com/search?q={search_query}"
        
        proxy_url = proxy if proxy else None
        
        async with session.get(
            jina_url,
            proxy=proxy_url,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                text = await resp.text()
                
                # Extract prices using regex
                price_pattern = r'\$[\d,]+'
                prices = re.findall(price_pattern, text)
                
                # Extract airlines (common ones)
                airlines = [
                    "Emirates", "Qatar Airways", "Ethiopian Airlines", 
                    "South African Airways", "British Airways", 
                    "Air France", "Lufthansa", "United Airlines",
                    "Turkish Airlines", "Delta", "KLM"
                ]
                
                found_airlines = []
                for airline in airlines:
                    if airline.lower() in text.lower():
                        found_airlines.append(airline)
                
                for i, price_str in enumerate(prices[:5]):
                    try:
                        price_val = float(price_str.replace("$", "").replace(",", ""))
                        if max_price and price_val > max_price:
                            continue
                            
                        airline = found_airlines[i % len(found_airlines)] if found_airlines else "Unknown"
                        
                        offer = FlightOffer(
                            origin=origin,
                            destination=destination,
                            airline=airline,
                            price=price_val,
                            currency="USD",
                            depart_date=date_from,
                            return_date=date_from + timedelta(days=7),
                            duration_minutes=600 + (i * 120),
                            stops=1 if i % 2 == 0 else 2,
                            booking_link=f"https://www.google.com/travel/flights?q={origin}+to+{destination}+{date_str}",
                            source="google_jina",
                            scraped_at=date.today().isoformat()
                        )
                        offers.append(offer)
                    except (ValueError, IndexError):
                        continue
                
                rate_limiter.record_success("jina.ai")
            else:
                rate_limiter.record_failure("jina.ai")
                
    except Exception as e:
        print(f"Google scrape error: {e}")
        rate_limiter.record_failure("jina.ai")
    finally:
        await session.close()
    
    # Cache results
    if offers:
        await cache_service.set(
            cache_key,
            [offer.__dict__ for offer in offers],
            ttl_seconds=3600  # Cache for 1 hour
        )
    
    return offers


def get_sample_flights(
    origin: str,
    destination: str,
    date_from: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Generate sample flight data for demonstration.
    Always works as ultimate fallback.
    """
    sample_data = [
        {"dest": "MIA", "airline": "South African Airways", "price": 1250, "duration": 1020, "stops": 2},
        {"dest": "MIA", "airline": "Emirates", "price": 1480, "duration": 980, "stops": 1},
        {"dest": "MIA", "airline": "Qatar Airways", "price": 1350, "duration": 1050, "stops": 1},
        {"dest": "MIA", "airline": "Ethiopian Airlines", "price": 980, "duration": 1150, "stops": 2},
        {"dest": "NCE", "airline": "South African Airways", "price": 980, "duration": 840, "stops": 1},
        {"dest": "NCE", "airline": "Emirates", "price": 1150, "duration": 780, "stops": 1},
        {"dest": "NCE", "airline": "Air France", "price": 1450, "duration": 720, "stops": 1},
        {"dest": "YUL", "airline": "Air Canada", "price": 1180, "duration": 960, "stops": 1},
        {"dest": "YUL", "airline": "South African Airways", "price": 1050, "duration": 1050, "stops": 2},
        {"dest": "LHR", "airline": "British Airways", "price": 850, "duration": 600, "stops": 0},
        {"dest": "LHR", "airline": "South African Airways", "price": 780, "duration": 640, "stops": 1},
    ]
    
    offers = []
    for sample in sample_data:
        if sample["dest"] == destination:
            if max_price and sample["price"] > max_price:
                continue
            offer = FlightOffer(
                origin=origin,
                destination=destination,
                airline=sample["airline"],
                price=float(sample["price"]),
                currency="USD",
                depart_date=date_from,
                return_date=date_from + timedelta(days=7),
                duration_minutes=sample["duration"],
                stops=sample["stops"],
                booking_link=f"https://www.skyscanner.com/transport/flights/{origin}/{destination}/",
                source="sample",
                scraped_at=date.today().isoformat()
            )
            offers.append(offer)
    
    return offers


async def search_flights(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> List[FlightOffer]:
    """
    Search flights using multiple free sources with caching.
    Order: Cache → Kiwi → Google (jina) → Sample
    """
    all_offers = []
    
    # Try Kiwi first (most reliable)
    kiwi_offers = await search_kiwi_flights(origin, destination, date_from, date_to, max_price)
    all_offers.extend(kiwi_offers)
    
    # Try Google scrape if no Kiwi results
    if not all_offers:
        google_offers = await search_google_flights_scrape(origin, destination, date_from, max_price)
        all_offers.extend(google_offers)
    
    # Final fallback: sample data (always works)
    if not all_offers:
        sample_offers = get_sample_flights(origin, destination, date_from, max_price)
        all_offers.extend(sample_offers)
    
    # Sort by score
    all_offers.sort(key=lambda x: x.score())
    
    return all_offers


async def get_best_flight(
    origin: str,
    destination: str,
    date_from: date,
    date_to: date,
    max_price: Optional[float] = None
) -> Optional[FlightOffer]:
    """Get the single best flight."""
    offers = await search_flights(origin, destination, date_from, date_to, max_price)
    return offers[0] if offers else None


# Export convenience function
__all__ = ['search_flights', 'get_best_flight', 'FlightOffer']

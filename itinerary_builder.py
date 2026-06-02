#!/usr/bin/env python3
"""
Itinerary Builder - Travel Scout

Combines neural search for events with scrapers for flights and hotels
to create complete travel itineraries.

Input: Event preferences, dates, location
Output: Structured itinerary with events + accommodation + transport
"""

import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import date, datetime, timedelta
from dataclasses import dataclass, asdict, field

# Add paths
NEURAL_INTEGRATION_PATH = Path(__file__).parent / "neural-integration"
BACKEND_PATH = Path(__file__).parent / "backend"
sys.path.insert(0, str(NEURAL_INTEGRATION_PATH))
sys.path.insert(0, str(BACKEND_PATH))

try:
    from travel_scout.search_router import SearchRouter
    from event_search import EventSearcher, EventResult, EventSearchError
    NEURAL_AVAILABLE = True
except ImportError as e:
    NEURAL_AVAILABLE = False
    logging.warning(f"Neural integration not available: {e}")

try:
    from app.scrapers.flight_scraper import search_flights, FlightOffer
    SCRAPERS_AVAILABLE = True
except ImportError as e:
    SCRAPERS_AVAILABLE = False
    logging.warning(f"Scrapers not available: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class Accommodation:
    """Hotel/accommodation details."""
    name: str
    location: str
    check_in: str
    check_out: str
    price_per_night: float
    currency: str = "USD"
    rating: Optional[float] = None
    amenities: List[str] = field(default_factory=list)
    booking_url: Optional[str] = None


@dataclass
class Transport:
    """Flight/transport details."""
    type: str = "flight"  # flight, train, bus
    origin: str = ""
    destination: str = ""
    outbound_date: Optional[str] = None
    return_date: Optional[str] = None
    airline: Optional[str] = None
    price: float = 0.0
    currency: str = "USD"
    duration_minutes: int = 0
    stops: int = 0
    booking_link: str = ""


@dataclass
class DayPlan:
    """Plan for a single day."""
    date: str
    events: List[EventResult] = field(default_factory=list)
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "events": [e.to_dict() for e in self.events],
            "notes": self.notes,
            "event_count": len(self.events)
        }


@dataclass
class Itinerary:
    """Complete travel itinerary."""
    title: str
    destination: str
    start_date: str
    end_date: str
    interests: List[str] = field(default_factory=list)
    
    # Components
    events: List[EventResult] = field(default_factory=list)
    accommodation: Optional[Accommodation] = None
    transport: Optional[Transport] = None
    
    # Daily breakdown
    days: List[DayPlan] = field(default_factory=list)
    
    # Costs
    estimated_total_cost: float = 0.0
    currency: str = "USD"
    cost_breakdown: Dict[str, float] = field(default_factory=dict)
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "travel_scout"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "destination": self.destination,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "interests": self.interests,
            "events": [e.to_dict() for e in self.events],
            "accommodation": asdict(self.accommodation) if self.accommodation else None,
            "transport": asdict(self.transport) if self.transport else None,
            "days": [d.to_dict() for d in self.days],
            "estimated_total_cost": self.estimated_total_cost,
            "currency": self.currency,
            "cost_breakdown": self.cost_breakdown,
            "created_at": self.created_at,
            "source": self.source,
            "duration_days": self.duration_days
        }
    
    @property
    def duration_days(self) -> int:
        """Calculate trip duration in days."""
        try:
            start = datetime.strptime(self.start_date, "%Y-%m-%d")
            end = datetime.strptime(self.end_date, "%Y-%m-%d")
            return (end - start).days + 1
        except (ValueError, TypeError):
            return 0
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


class ItineraryBuilderError(Exception):
    """Base exception for itinerary builder errors."""
    pass


class ItineraryBuilder:
    """
    Builds travel itineraries combining events, flights, and hotels.
    
    Uses Neural Search for event discovery and scrapers for travel logistics.
    """
    
    def __init__(
        self,
        event_searcher: Optional[EventSearcher] = None,
        router: Optional[SearchRouter] = None
    ):
        """
        Initialize itinerary builder.
        
        Args:
            event_searcher: Optional pre-configured EventSearcher
            router: Optional pre-configured SearchRouter
        """
        self.event_searcher = event_searcher
        self.router = router
        self._initialized = False
        
        if not NEURAL_AVAILABLE:
            raise ItineraryBuilderError("Neural search modules required")
        
        try:
            if self.router is None:
                self.router = SearchRouter()
            
            if self.event_searcher is None:
                self.event_searcher = EventSearcher(router=self.router)
            
            self._initialized = True
            logger.info("ItineraryBuilder initialized")
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise ItineraryBuilderError(f"Initialization failed: {e}")
    
    def _parse_dates(self, date_str: str) -> Tuple[date, date]:
        """Parse date range string (YYYY-MM-DD:YYYY-MM-DD)."""
        try:
            if ":" in date_str:
                start_str, end_str = date_str.split(":")
            else:
                # Single date - assume 3 day trip
                start_str = date_str
                start = datetime.strptime(start_str, "%Y-%m-%d").date()
                end = start + timedelta(days=2)
                return start, end
            
            start = datetime.strptime(start_str.strip(), "%Y-%m-%d").date()
            end = datetime.strptime(end_str.strip(), "%Y-%m-%d").date()
            return start, end
        except ValueError as e:
            raise ItineraryBuilderError(f"Invalid date format: {e}")
    
    def _extract_location_from_event(self, event: EventResult) -> Optional[str]:
        """Extract destination city from event."""
        # Try location first
        if event.location:
            return event.location.split(",")[0].strip()
        if event.city:
            return event.city
        
        # Try to extract from venue
        if event.venue:
            # Common venue patterns
            import re
            # "at Venue, City" pattern
            match = re.search(r",\s*([^,]+)$", event.venue)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _search_flights(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: date,
        max_price: Optional[float] = None
    ) -> Optional[Transport]:
        """Search for flights using scraper."""
        if not SCRAPERS_AVAILABLE:
            logger.warning("Flight scrapers not available")
            return None
        
        try:
            # Map common city names to airport codes
            airport_codes = {
                "london": "LHR",
                "paris": "CDG",
                "amsterdam": "AMS",
                "berlin": "BER",
                "madrid": "MAD",
                "rome": "FCO",
                "milan": "MXP",
                "monaco": "NCE",  # Closest major airport
                "silverstone": "LTN",  # Closest to Silverstone
                "budapest": "BUD",
                "spa": "BRU",  # Closest to Spa
                "singapore": "SIN",
                "austin": "AUS",
                "las vegas": "LAS",
                "miami": "MIA",
                "abu dhabi": "AUH",
                "dubai": "DXB",
                "jeddah": "JED",
                "suzuka": "NGO",
                "melbourne": "MEL",
                "sao paulo": "GRU",
                "são paulo": "GRU",
                "interlagos": "GRU",
                "shanghai": "PVG",
                "qatar": "DOH",
                "losail": "DOH",
                "bahrain": "BAH",
                "sakhir": "BAH",
                "barcelona": "BCN",
                "catalunya": "BCN",
                "montmelo": "BCN",
                "zandvoort": "AMS",
                "imola": "BLQ",
                "monza": "MXP",
                "red bull ring": "VIE",
                "spielberg": "VIE",
                "canada": "YUL",
                "montreal": "YUL",
                "villeneuve": "YUL",
            }
            
            origin_code = airport_codes.get(origin.lower(), origin)
            dest_code = airport_codes.get(destination.lower(), destination)
            
            logger.info(f"Searching flights: {origin_code} -> {dest_code}")
            
            # Run async flight search
            # Flight scraper interface: date_from, date_to (not depart_date, return_date)
            import asyncio
            flights = asyncio.run(search_flights(
                origin=origin_code,
                destination=dest_code,
                date_from=depart_date,
                date_to=return_date
            ))
            
            if flights:
                # Get best flight (first one, sorted by score)
                best = flights[0]
                return Transport(
                    type="flight",
                    origin=best.origin,
                    destination=best.destination,
                    outbound_date=str(best.depart_date),
                    return_date=str(best.return_date) if best.return_date else None,
                    airline=best.airline,
                    price=best.price,
                    currency=best.currency,
                    duration_minutes=best.duration_minutes,
                    stops=best.stops,
                    booking_link=best.booking_link
                )
        except Exception as e:
            logger.error(f"Flight search failed: {e}")
        
        return None
    
    def _build_daily_schedule(
        self,
        events: List[EventResult],
        start_date: date,
        end_date: date
    ) -> List[DayPlan]:
        """Build day-by-day schedule from events."""
        days = []
        current_date = start_date
        
        while current_date <= end_date:
            day_str = current_date.strftime("%Y-%m-%d")
            
            # Find events for this day
            day_events = []
            for event in events:
                if event.start_date:
                    try:
                        event_date = datetime.strptime(
                            event.start_date[:10], "%Y-%m-%d"
                        ).date()
                        if event_date == current_date:
                            day_events.append(event)
                    except (ValueError, TypeError):
                        pass
            
            day_plan = DayPlan(
                date=day_str,
                events=day_events,
                notes="" if day_events else "Free day - explore the city"
            )
            days.append(day_plan)
            
            current_date += timedelta(days=1)
        
        return days
    
    def _estimate_accommodation_cost(
        self,
        destination: str,
        nights: int,
        budget_level: str = "mid"
    ) -> Tuple[float, Optional[Accommodation]]:
        """Estimate hotel cost (fallback when scraper unavailable).
        
        NOTE: This bot cannot access real-time hotel data.
        Returns 0 cost and None accommodation to be honest with users.
        """
        logger.warning("Hotel scraper not available - cannot provide real hotel data")
        return 0.0, None
    
    def build_itinerary(
        self,
        event_query: str,
        dates: str,
        origin: str = "Maputo",
        interests: Optional[List[str]] = None,
        event_type: Optional[str] = None,
        budget_level: str = "mid",
        max_event_results: int = 10
    ) -> Itinerary:
        """
        Build a complete travel itinerary.
        
        Args:
            event_query: Search query for events (e.g., "F1 British GP")
            dates: Date range "YYYY-MM-DD:YYYY-MM-DD" or single date "YYYY-MM-DD"
            origin: Origin city (default: Maputo)
            interests: List of interests for event filtering (e.g., ["F1", "concerts"])
            event_type: Type of events to search (concert, f1, sports, festival)
            budget_level: Hotel budget level (budget, mid, luxury)
            max_event_results: Maximum events to include
            
        Returns:
            Complete Itinerary object
            
        Example:
            builder = ItineraryBuilder()
            itinerary = builder.build_itinerary(
                event_query="F1 British GP",
                dates="2026-07-18:2026-07-20",
                origin="Maputo",
                interests=["F1", "motorsport"]
            )
        """
        if not self._initialized:
            raise ItineraryBuilderError("Builder not initialized")
        
        interests = interests or []
        
        # Parse dates
        start_date, end_date = self._parse_dates(dates)
        nights = (end_date - start_date).days
        
        logger.info(f"Building itinerary: {event_query} from {start_date} to {end_date}")
        
        # Step 1: Search for events using neural search
        logger.info("Searching for events...")
        events = self.event_searcher.search(
            query=event_query,
            date_from=start_date,
            date_to=end_date,
            event_type=event_type,
            limit=max_event_results * 2
        )
        
        if not events:
            logger.warning("No events found for the specified criteria")
        
        # Limit to top events
        events = events[:max_event_results]
        
        # Step 2: Determine destination from events
        destination = None
        for event in events:
            dest = self._extract_location_from_event(event)
            if dest:
                destination = dest
                break
        
        if not destination:
            # Try to extract from query
            destination = event_query.split()[-1] if event_query else "Unknown"
            logger.warning(f"Could not determine destination from events, using: {destination}")
        
        # Step 3: Search for flights
        logger.info(f"Searching flights: {origin} -> {destination}")
        transport = self._search_flights(
            origin=origin,
            destination=destination,
            depart_date=start_date,
            return_date=end_date
        )
        
        # Step 4: Estimate accommodation
        logger.info(f"Estimating accommodation in {destination}")
        hotel_cost, accommodation = self._estimate_accommodation_cost(
            destination=destination,
            nights=nights,
            budget_level=budget_level
        )
        
        if accommodation:
            accommodation.check_in = start_date.strftime("%Y-%m-%d")
            accommodation.check_out = end_date.strftime("%Y-%m-%d")
        
        # Step 5: Build daily schedule
        days = self._build_daily_schedule(events, start_date, end_date)
        
        # Step 6: Calculate costs
        if transport:
            flight_cost = transport.price
        else:
            flight_cost = 0
        
        event_cost = len(events) * 100  # Rough estimate: $100 per event
        food_entertainment = nights * 50  # $50 per day food/entertainment
        
        total_cost = flight_cost + hotel_cost + event_cost + food_entertainment
        
        cost_breakdown = {
            "flights": flight_cost,
            "accommodation": hotel_cost,
            "events": event_cost,
            "food_entertainment": food_entertainment
        }
        
        # Step 7: Create itinerary
        itinerary = Itinerary(
            title=f"{event_query} Trip to {destination}",
            destination=destination,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            interests=interests,
            events=events,
            accommodation=accommodation,
            transport=transport,
            days=days,
            estimated_total_cost=total_cost,
            currency="USD",
            cost_breakdown=cost_breakdown
        )
        
        logger.info(f"Itinerary built: {len(events)} events, {nights} nights, ${total_cost:.2f} total")
        return itinerary
    
    def build_multi_event_itinerary(
        self,
        queries: List[str],
        dates: str,
        origin: str = "Maputo",
        interests: Optional[List[str]] = None,
        budget_level: str = "mid"
    ) -> Itinerary:
        """
        Build itinerary combining multiple event searches.
        
        Args:
            queries: List of event search queries
            dates: Date range
            origin: Origin city
            interests: List of interests
            budget_level: Budget level for hotels
            
        Returns:
            Combined itinerary with all events
        """
        if not self._initialized:
            raise ItineraryBuilderError("Builder not initialized")
        
        interests = interests or []
        start_date, end_date = self._parse_dates(dates)
        nights = (end_date - start_date).days
        
        # Collect events from all queries
        all_events = []
        for query in queries:
            logger.info(f"Searching: {query}")
            events = self.event_searcher.search(
                query=query,
                date_from=start_date,
                date_to=end_date,
                limit=5
            )
            all_events.extend(events)
        
        # Remove duplicates by title
        seen_titles = set()
        unique_events = []
        for event in all_events:
            if event.title not in seen_titles:
                seen_titles.add(event.title)
                unique_events.append(event)
        
        events = unique_events
        
        # Determine primary destination (most events)
        from collections import Counter
        locations = [self._extract_location_from_event(e) for e in events if self._extract_location_from_event(e)]
        destination = Counter(locations).most_common(1)[0][0] if locations else "Unknown"
        
        # Search flights and accommodation
        transport = self._search_flights(origin, destination, start_date, end_date)
        hotel_cost, accommodation = self._estimate_accommodation_cost(
            destination, nights, budget_level
        )
        
        if accommodation:
            accommodation.check_in = start_date.strftime("%Y-%m-%d")
            accommodation.check_out = end_date.strftime("%Y-%m-%d")
        
        # Build schedule
        days = self._build_daily_schedule(events, start_date, end_date)
        
        # Calculate costs
        flight_cost = transport.price if transport else 0
        total_cost = flight_cost + hotel_cost + (len(events) * 100) + (nights * 50)
        
        itinerary = Itinerary(
            title=f"Multi-Event Trip to {destination}",
            destination=destination,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            interests=interests,
            events=events,
            accommodation=accommodation,
            transport=transport,
            days=days,
            estimated_total_cost=total_cost,
            currency="USD",
            cost_breakdown={
                "flights": flight_cost,
                "accommodation": hotel_cost,
                "events": len(events) * 100,
                "food_entertainment": nights * 50
            }
        )
        
        return itinerary


def create_itinerary(
    event_query: str,
    dates: str,
    origin: str = "Maputo",
    interests: Optional[str] = None,
    event_type: Optional[str] = None,
    budget_level: str = "mid"
) -> Dict[str, Any]:
    """
    Convenience function to create an itinerary.
    
    Args:
        event_query: Search query for events
        dates: Date range "YYYY-MM-DD:YYYY-MM-DD"
        origin: Origin city
        interests: Comma-separated interests
        event_type: Type of events
        budget_level: Budget level
        
    Returns:
        Itinerary as dictionary
    """
    builder = ItineraryBuilder()
    
    # Parse interests
    interest_list = []
    if interests:
        interest_list = [i.strip() for i in interests.split(",")]
    
    itinerary = builder.build_itinerary(
        event_query=event_query,
        dates=dates,
        origin=origin,
        interests=interest_list,
        event_type=event_type,
        budget_level=budget_level
    )
    
    return itinerary.to_dict()


if __name__ == "__main__":
    # CLI usage
    import argparse
    
    parser = argparse.ArgumentParser(description="Build travel itineraries")
    parser.add_argument("--event", required=True, help="Event search query")
    parser.add_argument("--dates", required=True, help="Date range YYYY-MM-DD:YYYY-MM-DD")
    parser.add_argument("--origin", default="Maputo", help="Origin city")
    parser.add_argument("--interests", help="Comma-separated interests")
    parser.add_argument("--type", choices=["concert", "f1", "sports", "festival"], help="Event type")
    parser.add_argument("--budget", default="mid", choices=["budget", "mid", "luxury"])
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--save", help="Save to file")
    
    args = parser.parse_args()
    
    try:
        result = create_itinerary(
            event_query=args.event,
            dates=args.dates,
            origin=args.origin,
            interests=args.interests,
            event_type=args.type,
            budget_level=args.budget
        )
        
        if args.json:
            output = json.dumps(result, indent=2, default=str)
            print(output)
        else:
            # Pretty print
            print("\n" + "=" * 80)
            print(f"🎯 {result['title']}")
            print("=" * 80)
            print(f"\n📅 Dates: {result['start_date']} to {result['end_date']} ({result['duration_days']} days)")
            print(f"📍 Destination: {result['destination']}")
            if result['interests']:
                print(f"⭐ Interests: {', '.join(result['interests'])}")
            
            print(f"\n✈️  FLIGHTS:")
            if result['transport']:
                t = result['transport']
                print(f"   {t['origin']} → {t['destination']}")
                print(f"   Airline: {t['airline']}")
                print(f"   Price: ${t['price']:.2f} {t['currency']}")
                print(f"   Duration: {t['duration_minutes'] // 60}h {t['duration_minutes'] % 60}m")
                if t['booking_link']:
                    print(f"   Book: {t['booking_link']}")
            else:
                print("   ⚠️  FLIGHT DATA UNAVAILABLE")
                print("   This bot cannot access real-time flight prices.")
                print("   For actual flights Maputo → London, search:")
                print("   • Google Flights: https://flights.google.com")
                print("   • Kayak: https://www.kayak.com")
                print("   • Skyscanner: https://www.skyscanner.net")
                print("   • Or contact a travel agent")
            
            print(f"\n🏨 ACCOMMODATION:")
            if result['accommodation']:
                a = result['accommodation']
                print(f"   {a['name']}")
                print(f"   Check-in: {a['check_in']}, Check-out: {a['check_out']}")
                print(f"   Price: ${a['price_per_night']:.2f}/night")
                if a['rating']:
                    print(f"   Rating: {a['rating']}/5")
            
            print(f"\n🎪 EVENTS ({len(result['events'])} found):")
            for i, e in enumerate(result['events'], 1):
                print(f"\n   {i}. {e['title']}")
                print(f"      Type: {e['event_type'].upper()}")
                if e['venue']:
                    print(f"      Venue: {e['venue']}")
                if e['start_date']:
                    print(f"      Date: {e['start_date']}")
                if e['url']:
                    print(f"      URL: {e['url']}")
            
            print(f"\n💰 COST BREAKDOWN:")
            for category, cost in result['cost_breakdown'].items():
                if category == 'flights' and cost == 0:
                    print(f"   Flights: ⚠️  NOT INCLUDED (search manually)")
                else:
                    print(f"   {category.replace('_', ' ').title()}: ${cost:.2f}")
            
            if result['cost_breakdown'].get('flights', 0) == 0:
                print(f"\n   ⚠️  TOTAL: ${result['estimated_total_cost']:.2f} {result['currency']}")
                print(f"   (Plus flights - not included in estimate)")
            else:
                print(f"\n   TOTAL ESTIMATED: ${result['estimated_total_cost']:.2f} {result['currency']}")
            
            print(f"\n📋 DAILY SCHEDULE:")
            for day in result['days']:
                print(f"\n   {day['date']}:")
                if day['events']:
                    for e in day['events']:
                        print(f"      • {e['title']}")
                else:
                    print(f"      • {day['notes']}")
            
            print("\n" + "=" * 80)
        
        if args.save:
            with open(args.save, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\n💾 Saved to: {args.save}")
    
    except Exception as e:
        logger.error(f"Failed to build itinerary: {e}")
        sys.exit(1)
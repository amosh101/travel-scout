#!/usr/bin/env python3
"""
Event Search Module - Travel Scout

Uses Neural Search for event discovery with specialized queries for:
- Concerts and music events
- F1 races and motorsports
- Sports events
- Festivals and cultural events

Includes date range filtering and location-based search.
"""

import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import date, datetime
from dataclasses import dataclass, asdict

# Add neural-integration to path
NEURAL_INTEGRATION_PATH = Path(__file__).parent / "neural-integration"
sys.path.insert(0, str(NEURAL_INTEGRATION_PATH))

try:
    from travel_scout.search_router import SearchRouter, UnifiedSearchResponse
    from travel_scout.search_orchestrator import SearchSource
    NEURAL_AVAILABLE = True
except ImportError as e:
    NEURAL_AVAILABLE = False
    logging.warning(f"Neural integration not available: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class EventResult:
    """Standardized event result."""
    id: str
    title: str
    description: str
    event_type: str  # concert, f1, sports, festival
    venue: Optional[str] = None
    location: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    price_range: Optional[str] = None
    url: Optional[str] = None
    relevance_score: float = 0.0
    source: str = "neural"
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @property
    def date_obj(self) -> Optional[date]:
        """Parse start_date as date object."""
        if self.start_date:
            try:
                return datetime.strptime(self.start_date[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                pass
        return None


class EventSearchError(Exception):
    """Base exception for event search errors."""
    pass


class EventSearcher:
    """
    Event search using Neural Search as primary source.
    
    Specialized for:
    - Music events (concerts, festivals by genre)
    - F1 races and motorsports
    - Sports events
    - Cultural festivals
    """
    
    # Query templates for different event types
    QUERY_TEMPLATES = {
        "concert": [
            "{genre} concert {location}",
            "{genre} music festival {location}",
            "live music {genre} {location}",
            "{genre} artist tour {location}",
        ],
        "f1": [
            "F1 race {location}",
            "Formula 1 Grand Prix {location}",
            "F1 2026 calendar {location}",
            "F1 racing event {location}",
        ],
        "sports": [
            "sports event {location}",
            "football match {location}",
            "basketball game {location}",
            "tennis tournament {location}",
            "marathon {location}",
        ],
        "festival": [
            "music festival {location}",
            "cultural festival {location}",
            "arts festival {location}",
            "food festival {location}",
        ],
    }
    
    def __init__(self, router: Optional[SearchRouter] = None):
        """
        Initialize event searcher.
        
        Args:
            router: Optional pre-configured SearchRouter
        """
        self.router = router
        self._initialized = False
        
        if NEURAL_AVAILABLE:
            try:
                if self.router is None:
                    self.router = SearchRouter()
                self._initialized = True
                logger.info("EventSearcher initialized with neural search")
            except Exception as e:
                logger.error(f"Failed to initialize neural search: {e}")
                raise EventSearchError(f"Initialization failed: {e}")
        else:
            raise EventSearchError("Neural search modules not available")
    
    def _generate_queries(
        self,
        event_type: str,
        location: Optional[str],
        genre: Optional[str] = None
    ) -> List[str]:
        """Generate search queries based on event type."""
        queries = []
        templates = self.QUERY_TEMPLATES.get(event_type, self.QUERY_TEMPLATES["concert"])
        
        location_str = location if location else ""
        
        for template in templates:
            query = template.format(
                location=location_str,
                genre=genre or ""
            ).strip()
            # Remove double spaces
            query = " ".join(query.split())
            if query:
                queries.append(query)
        
        return queries
    
    def _parse_event_type(self, title: str, description: str) -> str:
        """Parse event type from content."""
        text = (title + " " + description).lower()
        
        if any(kw in text for kw in ["f1", "formula 1", "grand prix", "racing"]):
            return "f1"
        elif any(kw in text for kw in ["concert", "live music", "tour", "gig"]):
            return "concert"
        elif any(kw in text for kw in ["festival", "fest"]):
            return "festival"
        elif any(kw in text for kw in ["match", "game", "tournament", "championship", "cup"]):
            return "sports"
        else:
            return "other"
    
    def _extract_venue(self, text: str) -> Optional[str]:
        """Extract venue from text."""
        # Common venue patterns
        venue_patterns = [
            r"at\s+([A-Z][A-Za-z\s]+(?:Arena|Stadium|Center|Centre|Hall|Park|Gardens|Arena|Oval|Circuit|Track))",
            r"([A-Z][A-Za-z\s]+(?:Arena|Stadium|Center|Centre|Hall|Park|Gardens))",
        ]
        
        for pattern in venue_patterns:
            import re
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        return None
    
    def _extract_dates(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract dates from text."""
        import re
        
        # Look for date patterns
        date_patterns = [
            r"(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+202\d)",
            r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+202\d)",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{2}/\d{2}/\d{4})",
        ]
        
        dates = []
        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dates.extend(matches)
        
        if len(dates) >= 2:
            return dates[0], dates[1]
        elif len(dates) == 1:
            return dates[0], None
        
        return None, None
    
    def _convert_to_event(self, result: Any) -> EventResult:
        """Convert search result to EventResult."""
        # Handle both dataclass objects and dicts
        if hasattr(result, 'title'):
            # It's a dataclass (SearchResult)
            title = result.title
            description = result.description if result.description else ''
            result_id = result.id
            result_url = result.url
            relevance = result.relevance_score
            source = result.source
            metadata = result.metadata if result.metadata else {}
            location = result.location
        else:
            # It's a dict
            title = result.get('title', 'Unknown Event')
            description = result.get('description', '')
            result_id = result.get('id', '')
            result_url = result.get('url')
            relevance = result.get('relevance_score', 0.0)
            source = result.get('source', 'neural')
            metadata = result.get('metadata', {})
            location = result.get('location')
        
        event_type = self._parse_event_type(title, description)
        venue = self._extract_venue(title + " " + description)
        start_date, end_date = self._extract_dates(title + " " + description)
        
        # Try to get location from metadata if not set
        if not location and isinstance(metadata, dict):
            location = metadata.get('location')
        
        return EventResult(
            id=result_id,
            title=title,
            description=description[:500],
            event_type=event_type,
            venue=venue,
            location=location,
            city=None,  # Would need geocoding
            country=None,
            start_date=start_date,
            end_date=end_date,
            price_range=None,  # Would need extraction from description
            url=result_url,
            relevance_score=relevance,
            source=source
        )
    
    def _filter_by_date_range(
        self,
        events: List[EventResult],
        date_from: Optional[date],
        date_to: Optional[date]
    ) -> List[EventResult]:
        """Filter events by date range."""
        if not date_from and not date_to:
            return events
        
        filtered = []
        for event in events:
            event_date = event.date_obj
            
            if event_date is None:
                # Include events without dates
                filtered.append(event)
                continue
            
            if date_from and event_date < date_from:
                continue
            if date_to and event_date > date_to:
                continue
            
            filtered.append(event)
        
        return filtered
    
    def search(
        self,
        query: str,
        location: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        event_type: Optional[str] = None,
        limit: int = 20
    ) -> List[EventResult]:
        """
        Search for events using neural search.
        
        Args:
            query: Search query (e.g., "F1 races", "hip hop concerts London")
            location: Optional location filter
            date_from: Optional start date filter
            date_to: Optional end date filter
            event_type: Optional event type hint (concert, f1, sports, festival)
            limit: Maximum results to return
            
        Returns:
            List of EventResult objects
            
        Example:
            searcher = EventSearcher()
            events = searcher.search(
                query="F1 races",
                location="Europe",
                date_from=date(2026, 6, 1),
                date_to=date(2026, 8, 31)
            )
        """
        if not self._initialized:
            raise EventSearchError("Event searcher not initialized")
        
        logger.info(f"Searching events: '{query}' in {location or 'any location'}")
        
        # Perform unified search through router
        response = self.router.unified_search(
            query=query,
            location=location,
            date_range=(date_from, date_to) if date_from and date_to else None,
            search_type="events",
            limit=limit * 2  # Get extra for filtering
        )
        
        # Convert to EventResults
        events = [self._convert_to_event(r) for r in response.results]
        
        # Apply date filtering
        events = self._filter_by_date_range(events, date_from, date_to)
        
        # Apply event type filtering if specified
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # Sort by relevance
        events.sort(key=lambda e: e.relevance_score, reverse=True)
        
        # Limit results
        events = events[:limit]
        
        logger.info(f"Found {len(events)} events")
        return events
    
    def search_concerts(
        self,
        location: str,
        genre: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 10
    ) -> List[EventResult]:
        """
        Search for concerts by genre and location.
        
        Args:
            location: City or region
            genre: Music genre (e.g., "hip hop", "rock", "jazz")
            date_from: Optional start date
            date_to: Optional end date
            limit: Maximum results
            
        Returns:
            List of concert events
        """
        query = f"{genre or ''} concert {location}".strip()
        return self.search(
            query=query,
            location=location,
            date_from=date_from,
            date_to=date_to,
            event_type="concert",
            limit=limit
        )
    
    def search_f1_races(
        self,
        location: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 10
    ) -> List[EventResult]:
        """
        Search for F1 races.
        
        Args:
            location: Optional location filter
            date_from: Optional start date
            date_to: Optional end date
            limit: Maximum results
            
        Returns:
            List of F1 race events
        """
        query = f"F1 Formula 1 race {location or ''}".strip()
        return self.search(
            query=query,
            location=location,
            date_from=date_from,
            date_to=date_to,
            event_type="f1",
            limit=limit
        )
    
    def search_sports(
        self,
        location: str,
        sport_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 10
    ) -> List[EventResult]:
        """
        Search for sports events.
        
        Args:
            location: City or region
            sport_type: Type of sport (e.g., "football", "basketball", "tennis")
            date_from: Optional start date
            date_to: Optional end date
            limit: Maximum results
            
        Returns:
            List of sports events
        """
        query = f"{sport_type or ''} sports event {location}".strip()
        return self.search(
            query=query,
            location=location,
            date_from=date_from,
            date_to=date_to,
            event_type="sports",
            limit=limit
        )
    
    def search_festivals(
        self,
        location: str,
        festival_type: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        limit: int = 10
    ) -> List[EventResult]:
        """
        Search for festivals.
        
        Args:
            location: City or region
            festival_type: Type of festival (e.g., "music", "cultural", "food")
            date_from: Optional start date
            date_to: Optional end date
            limit: Maximum results
            
        Returns:
            List of festival events
        """
        query = f"{festival_type or ''} festival {location}".strip()
        return self.search(
            query=query,
            location=location,
            date_from=date_from,
            date_to=date_to,
            event_type="festival",
            limit=limit
        )


def search_events(
    query: str,
    location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 20
) -> List[EventResult]:
    """
    Convenience function for event search.
    
    Args:
        query: Search query
        location: Optional location
        date_from: Optional start date (YYYY-MM-DD format)
        date_to: Optional end date (YYYY-MM-DD format)
        event_type: Optional event type filter
        limit: Maximum results
        
    Returns:
        List of EventResult objects
    """
    searcher = EventSearcher()
    
    # Parse dates
    df = None
    dt = None
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid date_from format: {date_from}")
    
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(f"Invalid date_to format: {date_to}")
    
    return searcher.search(
        query=query,
        location=location,
        date_from=df,
        date_to=dt,
        event_type=event_type,
        limit=limit
    )


if __name__ == "__main__":
    # Demo usage
    import argparse
    
    parser = argparse.ArgumentParser(description="Search for events using Neural Search")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--location", help="Location filter")
    parser.add_argument("--date-from", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="End date (YYYY-MM-DD)")
    parser.add_argument("--type", choices=["concert", "f1", "sports", "festival"], help="Event type")
    parser.add_argument("--limit", type=int, default=10, help="Maximum results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    try:
        results = search_events(
            query=args.query,
            location=args.location,
            date_from=args.date_from,
            date_to=args.date_to,
            event_type=args.type,
            limit=args.limit
        )
        
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            print(f"\nFound {len(results)} events for: '{args.query}'\n")
            print("=" * 80)
            
            for i, event in enumerate(results, 1):
                print(f"\n{i}. {event.title}")
                print(f"   Type: {event.event_type.upper()}")
                if event.venue:
                    print(f"   Venue: {event.venue}")
                if event.location:
                    print(f"   Location: {event.location}")
                if event.start_date:
                    print(f"   Date: {event.start_date}")
                if event.price_range:
                    print(f"   Price: {event.price_range}")
                print(f"   Relevance: {event.relevance_score:.3f}")
                if event.url:
                    print(f"   URL: {event.url}")
                print(f"   {event.description[:200]}...")
            
            print("\n" + "=" * 80)
    
    except Exception as e:
        logger.error(f"Search failed: {e}")
        sys.exit(1)
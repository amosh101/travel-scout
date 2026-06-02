"""
Search Router - Main unified search interface for Travel Scout.

Provides a simple, consistent API for search operations across
Neural Search and legacy scrapers with automatic failover.

API Design:
    unified_search(query, location, date_range, search_type="auto")
    
    Returns: {
        source: "neural|scraper|hybrid",
        results: [...],
        latency_ms: int,
        cached: bool,
        failover_reason: str,
        metrics: {...}
    }
"""
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Union, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, date
from contextlib import asynccontextmanager

# Local imports
from .neural_client import NeuralClient, NeuralClientMock, create_client
from .search_orchestrator import (
    SearchOrchestrator, 
    OrchestratedResult, 
    SearchSource,
    SearchMetrics
)
from .index_sync import IndexSync, sync_flights, sync_hotels, sync_events

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Default config path
DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "search_config.json"


@dataclass
class SearchResult:
    """Standardized search result item."""
    id: str
    title: str
    description: str
    source: str
    url: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    location: Optional[str] = None
    date: Optional[str] = None
    relevance_score: float = 0.0
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass  
class UnifiedSearchResponse:
    """
    Standard response format for unified search.
    
    Attributes:
        source: Where results came from (neural, scraper, hybrid)
        results: List of search results
        latency_ms: Total search latency in milliseconds
        cached: Whether results came from cache
        query: Original search query
        search_type: Type of search performed
        failover_reason: Why failover occurred (if applicable)
        metrics: Detailed search metrics
        timestamp: When search was performed
    """
    source: str
    results: List[SearchResult]
    latency_ms: int
    cached: bool
    query: str
    search_type: str
    failover_reason: Optional[str] = None
    metrics: Optional[Dict] = None
    timestamp: str = None
    total_results: int = 0
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
        if self.total_results == 0:
            self.total_results = len(self.results)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "results": [r.to_dict() for r in self.results],
            "latency_ms": self.latency_ms,
            "cached": self.cached,
            "query": self.query,
            "search_type": self.search_type,
            "failover_reason": self.failover_reason,
            "metrics": self.metrics,
            "timestamp": self.timestamp,
            "total_results": self.total_results
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


class SearchRouter:
    """
    Main search router for Travel Scout.
    
    This is the primary interface for all search operations. It handles:
    - Query routing between neural search and scrapers
    - Result formatting and normalization
    - Caching and performance optimization
    - Metrics collection and reporting
    
    Usage:
        router = SearchRouter()
        results = router.unified_search(
            query="flights to London",
            location="Maputo",
            date_range=(date(2026, 6, 1), date(2026, 6, 7)),
            search_type="flights"
        )
    """
    
    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        neural_client: Optional[NeuralClient] = None,
        auto_register_scrapers: bool = True
    ):
        """
        Initialize the search router.
        
        Args:
            config_path: Path to search_config.json
            neural_client: Optional pre-configured neural client
            auto_register_scrapers: Automatically register default scrapers
        """
        self.config_path = Path(config_path or DEFAULT_CONFIG_PATH)
        self.config = self._load_config()
        
        # Initialize orchestrator
        self.orchestrator = SearchOrchestrator(
            config_path=str(self.config_path) if self.config_path.exists() else None,
            neural_client=neural_client
        )
        
        # Register scrapers if enabled
        if auto_register_scrapers:
            self._register_default_scrapers()
        
        # Track recent searches for analytics
        self.recent_searches: List[UnifiedSearchResponse] = []
        self.max_history = 100
        
        logger.info(f"SearchRouter initialized with config: {self.config_path}")
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}")
        
        return {}
    
    def _register_default_scrapers(self):
        """Register default scraper callbacks."""
        # These will be populated with actual scraper imports
        # For now, we create placeholder callbacks
        
        scraper_path = Path("/home/ubuntu/.openclaw/workspace/projects/travel-scout/backend/app/scrapers")
        
        if scraper_path.exists():
            try:
                # Import and register flight scraper
                import sys
                sys.path.insert(0, str(Path("/home/ubuntu/.openclaw/workspace/projects/travel-scout/backend")))
                
                from app.scrapers.flight_scraper import search_flights
                
                async def flight_scraper_callback(query, location, date_range):
                    """Wrapper for flight scraper."""
                    if not date_range:
                        date_range = (date.today(), date.today() + __import__('datetime').timedelta(days=7))
                    
                    # Extract origin/destination from query
                    # Simple heuristic: assume format like "flights from X to Y"
                    origin = "MPM"  # Default: Maputo
                    destination = None
                    
                    if "from" in query.lower() and "to" in query.lower():
                        parts = query.lower().split("to")
                        if len(parts) > 1:
                            destination = parts[1].strip().split()[0].upper()[:3]
                    
                    if destination:
                        import asyncio
                        results = await search_flights(origin, destination, date_range[0], date_range[1])
                        return [self._convert_flight_to_result(f) for f in results]
                    
                    return []
                
                self.orchestrator.register_scraper("flights", flight_scraper_callback)
                logger.info("Registered flight scraper")
                
            except Exception as e:
                logger.warning(f"Could not register flight scraper: {e}")
        
        # Register placeholder scrapers for other types
        def placeholder_scraper(query, location, date_range):
            logger.debug(f"Placeholder scraper called for: {query}")
            return []
        
        self.orchestrator.register_scraper("hotels", placeholder_scraper)
        self.orchestrator.register_scraper("events", placeholder_scraper)
    
    def _convert_flight_to_result(self, flight) -> Dict[str, Any]:
        """Convert FlightOffer to standardized result format."""
        return {
            "id": f"flight_{flight.origin}_{flight.destination}_{flight.depart_date}",
            "title": f"{flight.airline}: {flight.origin} → {flight.destination}",
            "description": (
                f"Flight from {flight.origin} to {flight.destination}. "
                f"Departure: {flight.depart_date}. "
                f"Duration: {flight.duration_minutes} minutes. "
                f"Stops: {flight.stops}."
            ),
            "source": "flight_scraper",
            "url": flight.booking_link,
            "price": flight.price,
            "currency": flight.currency,
            "date": str(flight.depart_date),
            "relevance_score": 0.9,
            "metadata": {
                "airline": flight.airline,
                "origin": flight.origin,
                "destination": flight.destination,
                "duration_minutes": flight.duration_minutes,
                "stops": flight.stops
            }
        }
    
    def unified_search(
        self,
        query: str,
        location: Optional[str] = None,
        date_range: Optional[tuple] = None,
        search_type: str = "auto",
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        force_source: Optional[str] = None
    ) -> UnifiedSearchResponse:
        """
        Perform a unified search across neural and scraper sources.
        
        This is the main entry point for search operations. It automatically
        routes between neural search and legacy scrapers based on query type,
        result quality, and configured thresholds.
        
        Args:
            query: Search query text (e.g., "flights to London", "hotels in Paris")
            location: Optional location context (city, region, etc.)
            date_range: Optional tuple of (start_date, end_date)
            search_type: Type of search - 'flights', 'hotels', 'events', or 'auto'
            filters: Optional filters to apply to results
            limit: Maximum number of results to return
            force_source: Force specific source ('neural', 'scraper', 'hybrid')
            
        Returns:
            UnifiedSearchResponse with results and metadata
            
        Example:
            router = SearchRouter()
            results = router.unified_search(
                query="flights to London",
                location="Maputo",
                date_range=(date(2026, 6, 1), date(2026, 6, 7)),
                search_type="flights"
            )
            
            for result in results.results:
                print(f"{result.title}: ${result.price}")
        """
        # Normalize inputs
        query = query.strip()
        if not query:
            return self._empty_response(query, search_type)
        
        # Map force_source string to enum
        force_source_enum = None
        if force_source:
            from .search_orchestrator import SearchSource
            try:
                force_source_enum = SearchSource(force_source.lower())
            except ValueError:
                logger.warning(f"Invalid force_source: {force_source}")
        
        # Execute search through orchestrator
        try:
            orchestrated_result = self.orchestrator.search(
                query=query,
                location=location,
                date_range=date_range,
                search_type=search_type,
                force_source=force_source_enum
            )
            
            # Convert to unified response format
            response = self._convert_to_unified_response(
                orchestrated_result,
                query,
                search_type
            )
            
            # Apply filters if provided
            if filters:
                response.results = self._apply_filters(response.results, filters)
                response.total_results = len(response.results)
            
            # Limit results
            if len(response.results) > limit:
                response.results = response.results[:limit]
                response.total_results = limit
            
            # Track in history
            self._add_to_history(response)
            
            return response
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return self._error_response(query, search_type, str(e))
    
    def _convert_to_unified_response(
        self,
        orchestrated: OrchestratedResult,
        query: str,
        search_type: str
    ) -> UnifiedSearchResponse:
        """Convert orchestrated result to unified response format."""
        # Convert results to SearchResult objects
        unified_results = []
        for r in orchestrated.results:
            result = SearchResult(
                id=r.get('id', ''),
                title=r.get('title', r.get('name', 'Unknown')),
                description=r.get('description', r.get('text', '')[:500]),
                source=r.get('source', r.get('data_type', 'unknown')),
                url=r.get('url', r.get('booking_link')),
                price=r.get('price'),
                currency=r.get('currency'),
                location=r.get('location'),
                date=r.get('date'),
                relevance_score=r.get('relevance_score', 0.5),
                metadata={k: v for k, v in r.items() if k not in [
                    'id', 'title', 'name', 'description', 'text', 'source',
                    'url', 'booking_link', 'price', 'currency', 'location',
                    'date', 'relevance_score', 'data_type'
                ]}
            )
            unified_results.append(result)
        
        return UnifiedSearchResponse(
            source=orchestrated.source.value,
            results=unified_results,
            latency_ms=orchestrated.latency_ms,
            cached=orchestrated.cached,
            query=query,
            search_type=search_type,
            failover_reason=orchestrated.failover_reason.value if orchestrated.failover_reason else None,
            metrics=orchestrated.metrics.to_dict() if orchestrated.metrics else None
        )
    
    def _apply_filters(
        self,
        results: List[SearchResult],
        filters: Dict[str, Any]
    ) -> List[SearchResult]:
        """Apply filters to results."""
        filtered = results
        
        # Price range filter
        if 'min_price' in filters:
            filtered = [r for r in filtered if r.price is None or r.price >= filters['min_price']]
        if 'max_price' in filters:
            filtered = [r for r in filtered if r.price is None or r.price <= filters['max_price']]
        
        # Source filter
        if 'source' in filters:
            filtered = [r for r in filtered if r.source == filters['source']]
        
        # Location filter
        if 'location_contains' in filters:
            filtered = [
                r for r in filtered
                if r.location and filters['location_contains'].lower() in r.location.lower()
            ]
        
        # Date filter (if results have dates)
        if 'after_date' in filters:
            from datetime import datetime
            try:
                after = datetime.fromisoformat(filters['after_date'])
                filtered = [
                    r for r in filtered
                    if r.date is None or datetime.fromisoformat(r.date) >= after
                ]
            except (ValueError, TypeError):
                pass
        
        return filtered
    
    def _empty_response(self, query: str, search_type: str) -> UnifiedSearchResponse:
        """Return empty response for empty query."""
        return UnifiedSearchResponse(
            source="neural",
            results=[],
            latency_ms=0,
            cached=False,
            query=query,
            search_type=search_type
        )
    
    def _error_response(
        self,
        query: str,
        search_type: str,
        error: str
    ) -> UnifiedSearchResponse:
        """Return error response."""
        return UnifiedSearchResponse(
            source="neural",
            results=[],
            latency_ms=0,
            cached=False,
            query=query,
            search_type=search_type,
            metrics={"error": error}
        )
    
    def _add_to_history(self, response: UnifiedSearchResponse):
        """Add search to history."""
        self.recent_searches.append(response)
        if len(self.recent_searches) > self.max_history:
            self.recent_searches.pop(0)
    
    def search_flights(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: Optional[date] = None,
        max_price: Optional[float] = None
    ) -> UnifiedSearchResponse:
        """
        Specialized flight search.
        
        Args:
            origin: Origin airport code (e.g., 'MPM')
            destination: Destination airport code (e.g., 'LHR')
            depart_date: Departure date
            return_date: Optional return date
            max_price: Optional maximum price filter
            
        Returns:
            UnifiedSearchResponse with flight results
        """
        query = f"flights from {origin} to {destination}"
        date_range = (depart_date, return_date or depart_date)
        
        filters = {}
        if max_price:
            filters['max_price'] = max_price
        
        return self.unified_search(
            query=query,
            search_type="flights",
            date_range=date_range,
            filters=filters
        )
    
    def search_hotels(
        self,
        location: str,
        check_in: date,
        check_out: date,
        max_price: Optional[float] = None,
        min_rating: Optional[float] = None
    ) -> UnifiedSearchResponse:
        """
        Specialized hotel search.
        
        Args:
            location: Hotel location (city or area)
            check_in: Check-in date
            check_out: Check-out date
            max_price: Optional maximum price per night
            min_rating: Optional minimum rating (1-5)
            
        Returns:
            UnifiedSearchResponse with hotel results
        """
        query = f"hotels in {location}"
        date_range = (check_in, check_out)
        
        filters = {'location_contains': location}
        if max_price:
            filters['max_price'] = max_price
        
        return self.unified_search(
            query=query,
            location=location,
            search_type="hotels",
            date_range=date_range,
            filters=filters
        )
    
    def search_events(
        self,
        location: str,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        event_type: Optional[str] = None
    ) -> UnifiedSearchResponse:
        """
        Specialized event search.
        
        Args:
            location: Event location (city)
            date_from: Optional start date
            date_to: Optional end date
            event_type: Optional event type (concert, sports, etc.)
            
        Returns:
            UnifiedSearchResponse with event results
        """
        query = f"{event_type or 'events'} in {location}"
        date_range = None
        if date_from and date_to:
            date_range = (date_from, date_to)
        
        return self.unified_search(
            query=query,
            location=location,
            search_type="events",
            date_range=date_range
        )
    
    def get_search_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent search history."""
        return [s.to_dict() for s in self.recent_searches[-limit:]]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get search metrics summary."""
        return self.orchestrator.get_metrics_summary()
    
    def sync_to_neural(
        self,
        data_type: str,
        data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Sync scraper data to neural search index.
        
        Args:
            data_type: Type of data ('flights', 'hotels', 'events')
            data: List of data items to index
            
        Returns:
            Sync result dictionary
        """
        try:
            if data_type == "flights":
                result = sync_flights(data)
            elif data_type == "hotels":
                result = sync_hotels(data)
            elif data_type == "events":
                result = sync_events(data)
            else:
                # Generic sync
                sync = IndexSync()
                result = sync.sync_documents(data)
            
            return result.to_dict()
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {"status": "failed", "error": str(e)}


# Convenience function for quick searches
def search(
    query: str,
    location: Optional[str] = None,
    **kwargs
) -> UnifiedSearchResponse:
    """
    Quick search function.
    
    Creates a SearchRouter instance and performs a search.
    For production use, create and reuse a SearchRouter instance.
    
    Args:
        query: Search query
        location: Optional location
        **kwargs: Additional arguments passed to unified_search
        
    Returns:
        UnifiedSearchResponse
    """
    router = SearchRouter()
    return router.unified_search(query, location, **kwargs)


# Create singleton instance for module-level access
_default_router: Optional[SearchRouter] = None

def get_router() -> SearchRouter:
    """Get or create default router instance."""
    global _default_router
    if _default_router is None:
        _default_router = SearchRouter()
    return _default_router
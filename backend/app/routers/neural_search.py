"""
Neural Search Router - Travel Scout API

Provides endpoints for neural search-powered event discovery
and itinerary building.
"""
import sys
from pathlib import Path
from typing import List, Optional
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

# Add neural-integration to path
NEURAL_INTEGRATION_PATH = Path(__file__).parent.parent.parent.parent / "neural-integration"
sys.path.insert(0, str(NEURAL_INTEGRATION_PATH))

try:
    from travel_scout.search_router import SearchRouter
    from event_search import EventSearcher, EventResult, search_events
    from itinerary_builder import ItineraryBuilder, create_itinerary
    NEURAL_AVAILABLE = True
except ImportError:
    NEURAL_AVAILABLE = False

from app.routers.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/api/neural", tags=["Neural Search"])


# Pydantic models for request/response
class EventSearchRequest(BaseModel):
    query: str = Field(..., description="Search query (e.g., 'F1 races', 'concerts London')")
    location: Optional[str] = Field(None, description="Location filter")
    date_from: Optional[date] = Field(None, description="Start date filter")
    date_to: Optional[date] = Field(None, description="End date filter")
    event_type: Optional[str] = Field(None, description="Event type: concert, f1, sports, festival")
    limit: int = Field(20, ge=1, le=100, description="Maximum results")


class EventSearchResponse(BaseModel):
    id: str
    title: str
    description: str
    event_type: str
    venue: Optional[str]
    location: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    price_range: Optional[str]
    url: Optional[str]
    relevance_score: float
    source: str


class ItineraryRequest(BaseModel):
    event_query: str = Field(..., description="Event search query")
    dates: str = Field(..., description="Date range YYYY-MM-DD:YYYY-MM-DD")
    origin: str = Field("Maputo", description="Origin city")
    interests: Optional[str] = Field(None, description="Comma-separated interests")
    event_type: Optional[str] = Field(None, description="Event type filter")
    budget_level: str = Field("mid", description="Budget level: budget, mid, luxury")


class DayPlanResponse(BaseModel):
    date: str
    events: List[EventSearchResponse]
    notes: str
    event_count: int


class CostBreakdown(BaseModel):
    flights: float
    accommodation: float
    events: float
    food_entertainment: float


class ItineraryResponse(BaseModel):
    title: str
    destination: str
    start_date: str
    end_date: str
    duration_days: int
    interests: List[str]
    events: List[EventSearchResponse]
    cost_breakdown: CostBreakdown
    estimated_total_cost: float
    currency: str
    days: List[DayPlanResponse]
    created_at: str


# Global router instance (initialized on first use)
_search_router: Optional[SearchRouter] = None
_event_searcher: Optional[EventSearcher] = None

def get_search_router() -> SearchRouter:
    """Get or create search router instance."""
    global _search_router
    if _search_router is None and NEURAL_AVAILABLE:
        _search_router = SearchRouter()
    return _search_router

def get_event_searcher() -> EventSearcher:
    """Get or create event searcher instance."""
    global _event_searcher
    if _event_searcher is None and NEURAL_AVAILABLE:
        router = get_search_router()
        _event_searcher = EventSearcher(router=router)
    return _event_searcher


@router.get("/health")
async def neural_search_health():
    """Check neural search system status."""
    return {
        "available": NEURAL_AVAILABLE,
        "router_initialized": _search_router is not None,
        "event_searcher_initialized": _event_searcher is not None
    }


@router.post("/events/search", response_model=List[EventSearchResponse])
async def search_events_endpoint(
    request: EventSearchRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Search for events using Neural Search.
    
    Uses the neural search system to find events like concerts, F1 races,
    sports events, and festivals based on semantic matching.
    """
    if not NEURAL_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Neural search system is not available"
        )
    
    try:
        results = search_events(
            query=request.query,
            location=request.location,
            date_from=request.date_from.isoformat() if request.date_from else None,
            date_to=request.date_to.isoformat() if request.date_to else None,
            event_type=request.event_type,
            limit=request.limit
        )
        
        return [EventSearchResponse(**r.to_dict()) for r in results]
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Search failed: {str(e)}"
        )


@router.get("/events/concerts")
async def search_concerts(
    location: str = Query(..., description="City or region"),
    genre: Optional[str] = Query(None, description="Music genre"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user)
):
    """Search for concerts by location and genre."""
    if not NEURAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Neural search not available")
    
    try:
        searcher = get_event_searcher()
        results = searcher.search_concerts(
            location=location,
            genre=genre,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        return [EventSearchResponse(**r.to_dict()) for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/events/f1")
async def search_f1_races(
    location: Optional[str] = Query(None, description="Optional location filter"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user)
):
    """Search for Formula 1 races."""
    if not NEURAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Neural search not available")
    
    try:
        searcher = get_event_searcher()
        results = searcher.search_f1_races(
            location=location,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        return [EventSearchResponse(**r.to_dict()) for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/events/sports")
async def search_sports(
    location: str = Query(..., description="City or region"),
    sport_type: Optional[str] = Query(None, description="Type of sport"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user)
):
    """Search for sports events."""
    if not NEURAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Neural search not available")
    
    try:
        searcher = get_event_searcher()
        results = searcher.search_sports(
            location=location,
            sport_type=sport_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        return [EventSearchResponse(**r.to_dict()) for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get("/events/festivals")
async def search_festivals(
    location: str = Query(..., description="City or region"),
    festival_type: Optional[str] = Query(None, description="Type of festival"),
    date_from: Optional[date] = Query(None, description="Start date"),
    date_to: Optional[date] = Query(None, description="End date"),
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user)
):
    """Search for festivals."""
    if not NEURAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Neural search not available")
    
    try:
        searcher = get_event_searcher()
        results = searcher.search_festivals(
            location=location,
            festival_type=festival_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit
        )
        return [EventSearchResponse(**r.to_dict()) for r in results]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/itinerary/build", response_model=ItineraryResponse)
async def build_itinerary_endpoint(
    request: ItineraryRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Build a complete travel itinerary.
    
    Combines neural search for events with scrapers for flights and hotels
to create a complete travel itinerary with cost estimates.
    """
    if not NEURAL_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail="Neural search system is not available"
        )
    
    try:
        result = create_itinerary(
            event_query=request.event_query,
            dates=request.dates,
            origin=request.origin,
            interests=request.interests,
            event_type=request.event_type,
            budget_level=request.budget_level
        )
        
        # Parse events for response
        events = [
            EventSearchResponse(**e) 
            for e in result.get('events', [])
        ]
        
        # Parse days
        days = []
        for day in result.get('days', []):
            day_events = [EventSearchResponse(**e) for e in day.get('events', [])]
            days.append(DayPlanResponse(
                date=day['date'],
                events=day_events,
                notes=day.get('notes', ''),
                event_count=len(day_events)
            ))
        
        # Parse cost breakdown
        cb = result.get('cost_breakdown', {})
        cost_breakdown = CostBreakdown(
            flights=cb.get('flights', 0),
            accommodation=cb.get('accommodation', 0),
            events=cb.get('events', 0),
            food_entertainment=cb.get('food_entertainment', 0)
        )
        
        return ItineraryResponse(
            title=result['title'],
            destination=result['destination'],
            start_date=result['start_date'],
            end_date=result['end_date'],
            duration_days=result['duration_days'],
            interests=result.get('interests', []),
            events=events,
            cost_breakdown=cost_breakdown,
            estimated_total_cost=result['estimated_total_cost'],
            currency=result['currency'],
            days=days,
            created_at=result['created_at']
        )
    
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Itinerary building failed: {str(e)}"
        )


@router.post("/unified/search")
async def unified_search_endpoint(
    query: str,
    location: Optional[str] = None,
    search_type: str = Query("auto", description="Type: flights, hotels, events, auto"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user)
):
    """
    Unified search across all sources.
    
    Uses the SearchRouter to intelligently route between neural search
    and scrapers based on query type and quality thresholds.
    """
    if not NEURAL_AVAILABLE:
        raise HTTPException(status_code=503, detail="Neural search not available")
    
    try:
        router = get_search_router()
        response = router.unified_search(
            query=query,
            location=location,
            search_type=search_type,
            limit=limit
        )
        
        return {
            "source": response.source,
            "results": [r.to_dict() for r in response.results],
            "total_results": response.total_results,
            "latency_ms": response.latency_ms,
            "cached": response.cached,
            "failover_reason": response.failover_reason,
            "query": response.query,
            "search_type": response.search_type
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
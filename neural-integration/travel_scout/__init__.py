"""
Travel Scout Neural Integration

Provides intelligent search routing between Neural Search and legacy scrapers.

Main Components:
- SearchRouter: Primary search interface
- SearchOrchestrator: Routing logic and failover
- NeuralClient: Neural search wrapper
- IndexSync: Data synchronization

Quick Start:
    from travel_scout import SearchRouter
    
    router = SearchRouter()
    results = router.unified_search(
        query="flights to London",
        location="Maputo",
        search_type="flights"
    )
"""

from .search_router import (
    SearchRouter,
    UnifiedSearchResponse,
    SearchResult,
    search,
    get_router
)
from .search_orchestrator import (
    SearchOrchestrator,
    OrchestratedResult,
    SearchSource,
    FailoverReason,
    SearchMetrics,
    QualityScore
)
from .neural_client import (
    NeuralClient,
    NeuralClientMock,
    NeuralSearchResponse,
    NeuralSearchResult,
    create_client
)
from .index_sync import (
    IndexSync,
    SyncResult,
    SyncStatus,
    sync_flights,
    sync_hotels,
    sync_events
)

__version__ = "1.0.0"
__all__ = [
    # Search Router
    "SearchRouter",
    "UnifiedSearchResponse", 
    "SearchResult",
    "search",
    "get_router",
    
    # Orchestrator
    "SearchOrchestrator",
    "OrchestratedResult",
    "SearchSource",
    "FailoverReason",
    "SearchMetrics",
    "QualityScore",
    
    # Neural Client
    "NeuralClient",
    "NeuralClientMock",
    "NeuralSearchResponse",
    "NeuralSearchResult",
    "create_client",
    
    # Index Sync
    "IndexSync",
    "SyncResult",
    "SyncStatus",
    "sync_flights",
    "sync_hotels",
    "sync_events"
]
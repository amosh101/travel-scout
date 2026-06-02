"""
Search Orchestrator - Intelligent routing between Neural Search and Scrapers.

Implements the core routing logic with automatic failover:
- Primary: Neural Search (fast, semantic, local)
- Fallback: Legacy Scrapers (live data, higher latency)

Trigger Conditions for Failover:
1. Neural returns < threshold results (default: 3)
2. Results are stale (> staleness_days old)
3. Specific venue/artist not found
4. User requests "live prices" or "current availability"
"""
import re
import json
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps

# Import local modules
from .neural_client import NeuralClient, NeuralClientMock, NeuralSearchResponse, NeuralSearchResult

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SearchSource(Enum):
    """Source of search results."""
    NEURAL = "neural"
    SCRAPER = "scraper"
    HYBRID = "hybrid"
    CACHE = "cache"


class FailoverReason(Enum):
    """Reason for triggering failover to scrapers."""
    NONE = "none"
    INSUFFICIENT_RESULTS = "insufficient_results"
    STALE_RESULTS = "stale_results"
    MISSING_ENTITY = "missing_entity"
    LIVE_DATA_REQUESTED = "live_data_requested"
    NEURAL_UNAVAILABLE = "neural_unavailable"
    SEARCH_ERROR = "search_error"


@dataclass
class QualityScore:
    """Quality metrics for search results."""
    relevance: float = 0.0
    freshness: float = 0.0
    completeness: float = 0.0
    diversity: float = 0.0
    overall: float = 0.0
    
    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class SearchMetrics:
    """Metrics for a search operation."""
    query: str
    source: SearchSource
    failover_reason: FailoverReason
    latency_ms: int
    neural_latency_ms: int = 0
    scraper_latency_ms: int = 0
    neural_result_count: int = 0
    scraper_result_count: int = 0
    quality_score: QualityScore = field(default_factory=QualityScore)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    cached: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "source": self.source.value,
            "failover_reason": self.failover_reason.value,
            "latency_ms": self.latency_ms,
            "neural_latency_ms": self.neural_latency_ms,
            "scraper_latency_ms": self.scraper_latency_ms,
            "neural_result_count": self.neural_result_count,
            "scraper_result_count": self.scraper_result_count,
            "quality_score": self.quality_score.to_dict(),
            "timestamp": self.timestamp,
            "cached": self.cached
        }


@dataclass
class OrchestratedResult:
    """Standardized search result from orchestrator."""
    source: SearchSource
    results: List[Dict[str, Any]]
    latency_ms: int
    cached: bool
    failover_reason: FailoverReason
    metrics: SearchMetrics
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.value,
            "results": self.results,
            "latency_ms": self.latency_ms,
            "cached": self.cached,
            "failover_reason": self.failover_reason.value,
            "metrics": self.metrics.to_dict(),
            "metadata": self.metadata
        }


class ScraperResult:
    """Result from a legacy scraper."""
    def __init__(
        self,
        data: Dict[str, Any],
        source_type: str,
        scraped_at: str = None
    ):
        self.data = data
        self.source_type = source_type
        self.scraped_at = scraped_at or datetime.now().isoformat()


class SearchOrchestrator:
    """
    Orchestrates search between Neural Search and Legacy Scrapers.
    
    Routing Logic:
    1. Try Neural Search first
    2. Check if results meet quality thresholds
    3. If not, fallback to scrapers
    4. Merge and deduplicate if hybrid mode
    
    Configuration:
    - neural_threshold: Minimum results from neural (default: 3)
    - staleness_days: Max age for neural results (default: 7)
    - collections: Which neural collections to search
    - fallback_enabled: Whether to use scrapers at all
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        neural_client: Optional[NeuralClient] = None,
        scraper_callbacks: Optional[Dict[str, Callable]] = None
    ):
        """
        Initialize the search orchestrator.
        
        Args:
            config_path: Path to search_config.json
            neural_client: Pre-configured NeuralClient instance
            scraper_callbacks: Dict of {search_type: callable} for scrapers
        """
        self.config = self._load_config(config_path)
        self.neural_client = neural_client or self._create_neural_client()
        self.scraper_callbacks = scraper_callbacks or {}
        self.metrics_history: List[SearchMetrics] = []
        self._ab_test_variant = None  # For A/B testing
        
        logger.info(
            f"SearchOrchestrator initialized: "
            f"neural_threshold={self.config.get('neural_threshold', 3)}, "
            f"staleness_days={self.config.get('staleness_days', 7)}"
        )
    
    def _load_config(self, config_path: Optional[str]) -> Dict[str, Any]:
        """Load orchestrator configuration."""
        default_config = {
            "primary_search": "neural",
            "fallback_enabled": True,
            "neural_threshold": 3,
            "staleness_days": 7,
            "collections": ["web", "events", "travel_data"],
            "auto_index": True,
            "cache_enabled": True,
            "cache_ttl_seconds": 300,
            "quality_metrics": {
                "min_result_score": 0.5,
                "max_latency_ms": 5000,
                "track_user_feedback": True
            }
        }
        
        if config_path:
            try:
                with open(config_path, 'r') as f:
                    loaded_config = json.load(f)
                    default_config.update(loaded_config)
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")
        
        return default_config
    
    def _create_neural_client(self) -> NeuralClient:
        """Create a new neural client from config."""
        neural_config = self.config.get('neural_search', {})
        try:
            return NeuralClient(
                db_path=neural_config.get('db_path'),
                embedding_model=neural_config.get('embedding_model')
            )
        except Exception as e:
            logger.error(f"Failed to create NeuralClient: {e}")
            logger.warning("Falling back to mock neural client")
            return NeuralClientMock()
    
    def register_scraper(
        self,
        search_type: str,
        callback: Callable[..., Any]
    ):
        """
        Register a scraper callback for a search type.
        
        Args:
            search_type: Type of search (e.g., 'flights', 'hotels', 'events')
            callback: Async or sync callable that performs the search
        """
        self.scraper_callbacks[search_type] = callback
        logger.info(f"Registered scraper for: {search_type}")
    
    def search(
        self,
        query: str,
        location: Optional[str] = None,
        date_range: Optional[tuple] = None,
        search_type: str = "auto",
        force_source: Optional[SearchSource] = None,
        user_preferences: Optional[Dict] = None
    ) -> OrchestratedResult:
        """
        Perform unified search with intelligent routing.
        
        Args:
            query: Search query text
            location: Location filter (city, region, etc.)
            date_range: Tuple of (start_date, end_date)
            search_type: Type of search ('flights', 'hotels', 'events', 'auto')
            force_source: Force specific source (for testing)
            user_preferences: Additional user preferences
            
        Returns:
            OrchestratedResult with results and metadata
        """
        start_time = time.time()
        
        # Check for live data keywords
        failover_reason = self._check_live_data_keywords(query)
        
        # Determine source
        if force_source:
            source = force_source
        elif failover_reason != FailoverReason.NONE:
            source = SearchSource.SCRAPER if self.config.get('fallback_enabled') else SearchSource.NEURAL
        else:
            source = SearchSource.NEURAL
        
        # Execute search based on source
        neural_response = None
        scraper_results = []
        neural_latency = 0
        scraper_latency = 0
        
        try:
            if source in [SearchSource.NEURAL, SearchSource.HYBRID]:
                neural_response, neural_latency = self._search_neural(
                    query, location, search_type
                )
                
                # Check if we need to failover
                if source == SearchSource.NEURAL:
                    failover_reason = self._should_failover(neural_response)
                    if failover_reason != FailoverReason.NONE and self.config.get('fallback_enabled'):
                        source = SearchSource.HYBRID
            
            if source in [SearchSource.SCRAPER, SearchSource.HYBRID]:
                scraper_results, scraper_latency = self._search_scrapers(
                    query, location, date_range, search_type
                )
                
                if source == SearchSource.HYBRID:
                    source = SearchSource.HYBRID
                else:
                    source = SearchSource.SCRAPER
            
            # Merge results if hybrid
            if source == SearchSource.HYBRID:
                final_results = self._merge_results(neural_response, scraper_results)
            elif neural_response:
                final_results = self._convert_neural_results(neural_response.results)
            else:
                final_results = scraper_results
            
            # Calculate quality score
            quality = self._calculate_quality_score(final_results, source)
            
            # Build metrics
            total_latency = int((time.time() - start_time) * 1000)
            metrics = SearchMetrics(
                query=query,
                source=source,
                failover_reason=failover_reason,
                latency_ms=total_latency,
                neural_latency_ms=neural_latency,
                scraper_latency_ms=scraper_latency,
                neural_result_count=len(neural_response.results) if neural_response else 0,
                scraper_result_count=len(scraper_results),
                quality_score=quality
            )
            
            self.metrics_history.append(metrics)
            
            # Build result
            result = OrchestratedResult(
                source=source,
                results=final_results,
                latency_ms=total_latency,
                cached=neural_response.cached if neural_response else False,
                failover_reason=failover_reason,
                metrics=metrics,
                metadata={
                    "neural_collections_searched": neural_response.collections_searched if neural_response else [],
                    "scrapers_used": list(self.scraper_callbacks.keys()) if scraper_results else [],
                    "threshold": self.config.get('neural_threshold', 3),
                    "staleness_days": self.config.get('staleness_days', 7)
                }
            )
            
            logger.info(
                f"Search completed: source={source.value}, "
                f"results={len(final_results)}, latency={total_latency}ms, "
                f"failover={failover_reason.value}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Search orchestration failed: {e}")
            # Return empty result with error
            return OrchestratedResult(
                source=SearchSource.NEURAL,
                results=[],
                latency_ms=int((time.time() - start_time) * 1000),
                cached=False,
                failover_reason=FailoverReason.SEARCH_ERROR,
                metrics=SearchMetrics(
                    query=query,
                    source=SearchSource.NEURAL,
                    failover_reason=FailoverReason.SEARCH_ERROR,
                    latency_ms=int((time.time() - start_time) * 1000)
                ),
                metadata={"error": str(e)}
            )
    
    def _search_neural(
        self,
        query: str,
        location: Optional[str],
        search_type: str
    ) -> tuple[Optional[NeuralSearchResponse], int]:
        """Execute neural search and return response + latency."""
        if not self.neural_client.is_initialized():
            return None, 0
        
        start = time.time()
        
        try:
            # Enhance query with location if provided
            enhanced_query = query
            if location:
                enhanced_query = f"{query} in {location}"
            
            # Determine collections based on search type
            collections = self.config.get('collections', ['web', 'events'])
            if search_type == 'flights':
                collections = ['travel_data', 'web']
            elif search_type == 'hotels':
                collections = ['travel_data', 'web']
            elif search_type == 'events':
                collections = ['events', 'web']
            
            response = self.neural_client.search(
                query=enhanced_query,
                collections=collections,
                limit=20,
                threshold=self.config.get('quality_metrics', {}).get('min_result_score', 0.3),
                rerank=True
            )
            
            latency = int((time.time() - start) * 1000)
            return response, latency
            
        except Exception as e:
            logger.error(f"Neural search failed: {e}")
            return None, int((time.time() - start) * 1000)
    
    def _search_scrapers(
        self,
        query: str,
        location: Optional[str],
        date_range: Optional[tuple],
        search_type: str
    ) -> tuple[List[Dict], int]:
        """Execute scraper search and return results + latency."""
        start = time.time()
        results = []
        
        # Determine which scrapers to use
        scrapers_to_use = []
        if search_type == 'auto':
            scrapers_to_use = list(self.scraper_callbacks.keys())
        elif search_type in self.scraper_callbacks:
            scrapers_to_use = [search_type]
        
        for scraper_name in scrapers_to_use:
            try:
                callback = self.scraper_callbacks[scraper_name]
                scraper_result = callback(
                    query=query,
                    location=location,
                    date_range=date_range
                )
                
                if isinstance(scraper_result, list):
                    results.extend(scraper_result)
                elif scraper_result:
                    results.append(scraper_result)
                    
            except Exception as e:
                logger.error(f"Scraper {scraper_name} failed: {e}")
        
        latency = int((time.time() - start) * 1000)
        return results, latency
    
    def _check_live_data_keywords(self, query: str) -> FailoverReason:
        """Check if query contains live data keywords."""
        live_keywords = [
            r'live\s+price',
            r'current\s+availability',
            r'real[-\s]?time',
            r'now\s+available',
            r'check\s+price',
            r'live\s+booking',
            r'up[-\s]?to[-\s]?date',
            r'today\s+price',
            r'latest\s+price',
            r'current\s+status'
        ]
        
        query_lower = query.lower()
        for keyword in live_keywords:
            if re.search(keyword, query_lower):
                logger.info(f"Live data keyword detected: {keyword}")
                return FailoverReason.LIVE_DATA_REQUESTED
        
        return FailoverReason.NONE
    
    def _should_failover(
        self,
        neural_response: Optional[NeuralSearchResponse]
    ) -> FailoverReason:
        """Determine if we should failover to scrapers."""
        if neural_response is None:
            logger.info("Failover: Neural search unavailable")
            return FailoverReason.NEURAL_UNAVAILABLE
        
        threshold = self.config.get('neural_threshold', 3)
        
        # Check result count
        if len(neural_response.results) < threshold:
            logger.info(f"Failover: Insufficient results ({len(neural_response.results)} < {threshold})")
            return FailoverReason.INSUFFICIENT_RESULTS
        
        # Check staleness
        staleness_days = self.config.get('staleness_days', 7)
        stale_count = sum(
            1 for r in neural_response.results
            if self.neural_client.is_result_stale(r, staleness_days)
        )
        
        if stale_count > len(neural_response.results) / 2:
            logger.info(f"Failover: Too many stale results ({stale_count}/{len(neural_response.results)})")
            return FailoverReason.STALE_RESULTS
        
        return FailoverReason.NONE
    
    def _convert_neural_results(
        self,
        neural_results: List[NeuralSearchResult]
    ) -> List[Dict[str, Any]]:
        """Convert neural results to standard format."""
        return [
            {
                "id": r.id,
                "title": r.title,
                "description": r.text[:500],
                "url": r.url,
                "source": r.source_type,
                "collection": r.collection,
                "relevance_score": r.similarity,
                "indexed_at": r.indexed_at,
                "data_type": "neural",
                "metadata": r.metadata
            }
            for r in neural_results
        ]
    
    def _merge_results(
        self,
        neural_response: Optional[NeuralSearchResponse],
        scraper_results: List[Dict]
    ) -> List[Dict[str, Any]]:
        """Merge neural and scraper results, removing duplicates."""
        merged = []
        seen_urls = set()
        
        # Add neural results first (higher relevance)
        if neural_response:
            for r in neural_response.results:
                result = self._convert_neural_results([r])[0]
                if result['url'] not in seen_urls:
                    merged.append(result)
                    seen_urls.add(result['url'])
        
        # Add scraper results
        for r in scraper_results:
            url = r.get('url') or r.get('booking_link')
            if url and url not in seen_urls:
                merged.append(r)
                seen_urls.add(url)
        
        return merged
    
    def _calculate_quality_score(
        self,
        results: List[Dict],
        source: SearchSource
    ) -> QualityScore:
        """Calculate quality metrics for results."""
        if not results:
            return QualityScore()
        
        # Relevance: average of relevance scores (or default 0.7 for scraper)
        relevance_scores = [
            r.get('relevance_score', 0.7 if source != SearchSource.NEURAL else 0.5)
            for r in results
        ]
        relevance = sum(relevance_scores) / len(relevance_scores)
        
        # Freshness: ratio of non-stale results
        # For scrapers, all are considered fresh
        freshness = 1.0 if source == SearchSource.SCRAPER else 0.8
        
        # Completeness: do results have key fields
        required_fields = ['title', 'url']
        complete_count = sum(
            1 for r in results
            if all(f in r and r[f] for f in required_fields)
        )
        completeness = complete_count / len(results)
        
        # Diversity: variety of sources
        sources = set(r.get('source', 'unknown') for r in results)
        diversity = min(len(sources) / 3, 1.0)  # Max at 3+ sources
        
        # Overall: weighted average
        overall = (relevance * 0.4) + (freshness * 0.3) + (completeness * 0.2) + (diversity * 0.1)
        
        return QualityScore(
            relevance=round(relevance, 2),
            freshness=round(freshness, 2),
            completeness=round(completeness, 2),
            diversity=round(diversity, 2),
            overall=round(overall, 2)
        )
    
    def get_metrics_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get summary of search metrics."""
        cutoff = datetime.now() - timedelta(days=days)
        recent = [m for m in self.metrics_history if datetime.fromisoformat(m.timestamp) > cutoff]
        
        if not recent:
            return {"message": "No metrics available"}
        
        neural_count = sum(1 for m in recent if m.source == SearchSource.NEURAL)
        scraper_count = sum(1 for m in recent if m.source == SearchSource.SCRAPER)
        hybrid_count = sum(1 for m in recent if m.source == SearchSource.HYBRID)
        
        avg_latency = sum(m.latency_ms for m in recent) / len(recent)
        avg_neural_results = sum(m.neural_result_count for m in recent) / len(recent)
        avg_scraper_results = sum(m.scraper_result_count for m in recent) / len(recent)
        
        failover_reasons = {}
        for m in recent:
            reason = m.failover_reason.value
            failover_reasons[reason] = failover_reasons.get(reason, 0) + 1
        
        return {
            "period_days": days,
            "total_searches": len(recent),
            "source_breakdown": {
                "neural": neural_count,
                "scraper": scraper_count,
                "hybrid": hybrid_count
            },
            "average_latency_ms": round(avg_latency, 2),
            "average_neural_results": round(avg_neural_results, 2),
            "average_scraper_results": round(avg_scraper_results, 2),
            "failover_reasons": failover_reasons
        }
    
    def clear_metrics(self):
        """Clear metrics history."""
        self.metrics_history.clear()
        logger.info("Metrics history cleared")


# Convenience function for quick searches
def orchestrated_search(
    query: str,
    location: Optional[str] = None,
    date_range: Optional[tuple] = None,
    search_type: str = "auto",
    config_path: Optional[str] = None
) -> OrchestratedResult:
    """
    Quick search using the orchestrator.
    
    Args:
        query: Search query
        location: Optional location
        date_range: Optional (start, end) dates
        search_type: Type of search
        config_path: Optional config file path
        
    Returns:
        OrchestratedResult
    """
    orchestrator = SearchOrchestrator(config_path=config_path)
    return orchestrator.search(query, location, date_range, search_type)
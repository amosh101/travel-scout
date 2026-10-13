"""
Neural Search Client - Wrapper for the Neural Search System.

Provides a clean Python interface to the neural search functionality
for use within the Travel Scout application.
"""
import sys
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from datetime import datetime, timedelta

# Add neural-search to path
NEURAL_SEARCH_PATH = Path("/home/ubuntu/.openclaw/workspace/projects/neural-search")
sys.path.insert(0, str(NEURAL_SEARCH_PATH))

try:
    from src.config import NeuralSearchConfig
    from src.embeddings import EmbeddingEngine, CrossEncoderReranker
    from src.vector_store import VectorStore
    NEURAL_SEARCH_AVAILABLE = True
except ImportError as e:
    NEURAL_SEARCH_AVAILABLE = False
    logging.warning(f"Neural search modules not available: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class NeuralSearchResult:
    """Standardized neural search result."""
    id: str
    text: str
    title: str
    url: str
    source_type: str
    collection: str
    similarity: float
    indexed_at: Optional[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class NeuralSearchResponse:
    """Complete search response with metadata."""
    query: str
    results: List[NeuralSearchResult]
    latency_ms: int
    result_count: int
    collections_searched: List[str]
    timestamp: str
    cached: bool = False
    reranked: bool = False


class NeuralClientError(Exception):
    """Base exception for neural client errors."""
    pass


class NeuralClientConfigError(NeuralClientError):
    """Configuration error."""
    pass


class NeuralSearchError(NeuralClientError):
    """Search operation error."""
    pass


class NeuralClient:
    """
    Client for the Neural Search System.
    
    Provides semantic search capabilities with automatic embedding generation
    and cross-collection querying.
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        db_path: Optional[str] = None,
        embedding_model: Optional[str] = None
    ):
        """
        Initialize the neural search client.
        
        Args:
            config_path: Path to neural search config file
            db_path: Override for database path
            embedding_model: Override for embedding model
        """
        self.config = None
        self.embedding_engine = None
        self.vector_store = None
        self.reranker = None
        self._initialized = False
        self._last_cache_clear = datetime.now()
        self._result_cache = {}
        
        if not NEURAL_SEARCH_AVAILABLE:
            raise NeuralClientConfigError(
                "Neural search modules not available. "
                "Ensure the neural-search project is properly installed."
            )
        
        try:
            # Load configuration
            self.config = NeuralSearchConfig.from_file(config_path)
            
            # Apply overrides
            if db_path:
                self.config.db_path = db_path
            if embedding_model:
                self.config.embedding_model = embedding_model
            
            # Initialize embedding engine
            logger.info(f"Loading embedding model: {self.config.embedding_model}")
            self.embedding_engine = EmbeddingEngine(self.config.embedding_model)
            
            # Initialize vector store
            logger.info(f"Connecting to vector store at: {self.config.db_path}")
            self.vector_store = VectorStore(
                self.config.get_db_path(),
                self.embedding_engine
            )
            
            self._initialized = True
            logger.info("Neural client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize neural client: {e}")
            raise NeuralClientConfigError(f"Initialization failed: {e}")
    
    def is_initialized(self) -> bool:
        """Check if client is properly initialized."""
        return self._initialized
    
    def search(
        self,
        query: str,
        collections: Optional[List[str]] = None,
        limit: int = 10,
        threshold: float = 0.3,
        rerank: bool = False,
        use_cache: bool = True
    ) -> NeuralSearchResponse:
        """
        Perform semantic search.
        
        Args:
            query: Search query text
            collections: Collections to search (None = all available)
            limit: Maximum results to return
            threshold: Minimum similarity threshold (0.0-1.0)
            rerank: Whether to apply cross-encoder reranking
            use_cache: Whether to use result caching
            
        Returns:
            NeuralSearchResponse with results and metadata
        """
        if not self._initialized:
            raise NeuralSearchError("Client not initialized")
        
        start_time = time.time()
        
        # Check cache
        cache_key = f"{query}:{','.join(collections or [])}:{limit}:{threshold}"
        if use_cache and cache_key in self._result_cache:
            cached_response = self._result_cache[cache_key]
            cached_response.cached = True
            return cached_response
        
        try:
            # Determine collections to search
            if collections is None:
                # Get available collections from vector store
                available_collections = [
                    c.name for c in self.vector_store.client.list_collections()
                ]
                collections = available_collections
            else:
                # Map collection aliases to actual names
                collections = [
                    self.config.collections.get(c, c) for c in collections
                ]
            
            if not collections:
                logger.warning("No collections available for search")
                return NeuralSearchResponse(
                    query=query,
                    results=[],
                    latency_ms=0,
                    result_count=0,
                    collections_searched=[],
                    timestamp=datetime.now().isoformat()
                )
            
            # Perform search
            raw_results = self.vector_store.search(
                query=query,
                collection_names=collections,
                limit=limit * 2 if rerank else limit,  # Get more for reranking
                threshold=threshold
            )
            
            # Rerank if requested and we have results
            if rerank and raw_results and len(raw_results) > 1:
                raw_results = self._rerank_results(query, raw_results, limit)
            
            # Limit to requested amount
            raw_results = raw_results[:limit]
            
            # Convert to standardized results
            results = [self._convert_result(r) for r in raw_results]
            
            # Build response
            latency_ms = int((time.time() - start_time) * 1000)
            response = NeuralSearchResponse(
                query=query,
                results=results,
                latency_ms=latency_ms,
                result_count=len(results),
                collections_searched=collections,
                timestamp=datetime.now().isoformat(),
                cached=False,
                reranked=rerank
            )
            
            # Cache result
            if use_cache:
                self._result_cache[cache_key] = response
                self._clear_stale_cache()
            
            return response
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise NeuralSearchError(f"Search operation failed: {e}")
    
    def _rerank_results(
        self,
        query: str,
        results: List[Dict],
        top_k: int
    ) -> List[Dict]:
        """Rerank results using cross-encoder."""
        try:
            if self.reranker is None:
                self.reranker = CrossEncoderReranker(self.config.reranker_model)
            
            texts = [r['text'] for r in results]
            reranked = self.reranker.rerank(query, texts, top_k=top_k)
            
            # Reorder results
            reranked_results = []
            for idx, score in reranked:
                result = results[idx].copy()
                result['similarity'] = score
                reranked_results.append(result)
            
            return reranked_results
            
        except Exception as e:
            logger.warning(f"Reranking failed: {e}")
            return results[:top_k]
    
    def _convert_result(self, raw_result: Dict) -> NeuralSearchResult:
        """Convert raw vector store result to standardized format."""
        metadata = raw_result.get('metadata', {})
        
        return NeuralSearchResult(
            id=raw_result.get('id', ''),
            text=raw_result.get('text', ''),
            title=metadata.get('title', ''),
            url=metadata.get('url', ''),
            source_type=metadata.get('source_type', 'unknown'),
            collection=raw_result.get('collection', ''),
            similarity=raw_result.get('similarity', 0.0),
            indexed_at=metadata.get('indexed_at'),
            metadata=metadata
        )
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about available collections."""
        if not self._initialized:
            return {"error": "Client not initialized"}
        
        try:
            return self.vector_store.get_stats()
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"error": str(e)}
    
    def check_collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists."""
        try:
            available = [c.name for c in self.vector_store.client.list_collections()]
            actual_name = self.config.collections.get(collection_name, collection_name)
            return actual_name in available
        except Exception:
            return False
    
    def get_result_staleness(self, result: NeuralSearchResult) -> Optional[int]:
        """
        Calculate staleness in days for a result.
        
        Returns:
            Number of days since indexed, or None if unknown
        """
        if not result.indexed_at:
            return None
        
        try:
            indexed_date = datetime.fromisoformat(result.indexed_at)
            return (datetime.now() - indexed_date).days
        except (ValueError, TypeError):
            return None
    
    def is_result_stale(self, result: NeuralSearchResult, max_days: int = 7) -> bool:
        """Check if a result is considered stale."""
        staleness = self.get_result_staleness(result)
        if staleness is None:
            return True  # Unknown age = assume stale
        return staleness > max_days
    
    def filter_stale_results(
        self,
        results: List[NeuralSearchResult],
        max_days: int = 7
    ) -> List[NeuralSearchResult]:
        """Filter out results older than max_days."""
        return [r for r in results if not self.is_result_stale(r, max_days)]
    
    def clear_cache(self):
        """Clear the result cache."""
        self._result_cache.clear()
        self._last_cache_clear = datetime.now()
        logger.info("Result cache cleared")
    
    def _clear_stale_cache(self, max_age_minutes: int = 60):
        """Clear cache entries older than max_age_minutes."""
        # Simple implementation - could be enhanced with per-entry timestamps
        elapsed_minutes = (datetime.now() - self._last_cache_clear).total_seconds() / 60
        if elapsed_minutes > max_age_minutes:
            self.clear_cache()


class NeuralClientMock:
    """Mock neural client for testing or when neural search is unavailable."""
    
    def __init__(self):
        self._initialized = True
        logger.info("Using mock neural client")
    
    def is_initialized(self) -> bool:
        return True
    
    def search(
        self,
        query: str,
        collections: Optional[List[str]] = None,
        limit: int = 10,
        threshold: float = 0.3,
        rerank: bool = False,
        use_cache: bool = True
    ) -> NeuralSearchResponse:
        """Return mock results."""
        logger.debug(f"Mock search: {query}")
        
        # Generate mock results based on query
        mock_results = [
            NeuralSearchResult(
                id=f"mock_{i}",
                text=f"Mock result for '{query}' - item {i}",
                title=f"Mock Title {i}",
                url=f"https://example.com/{i}",
                source_type="mock",
                collection=collections[0] if collections else "mock",
                similarity=0.8 - (i * 0.1),
                indexed_at=datetime.now().isoformat(),
                metadata={}
            )
            for i in range(min(limit, 3))
        ]
        
        return NeuralSearchResponse(
            query=query,
            results=mock_results,
            latency_ms=10,
            result_count=len(mock_results),
            collections_searched=collections or ["mock"],
            timestamp=datetime.now().isoformat(),
            cached=False,
            reranked=False
        )
    
    def get_collection_stats(self) -> Dict[str, Any]:
        return {"collections": {"mock": {"document_count": 100}}}
    
    def check_collection_exists(self, collection_name: str) -> bool:
        return True
    
    def is_result_stale(self, result: NeuralSearchResult, max_days: int = 7) -> bool:
        return False


def create_client(
    config_path: Optional[str] = None,
    mock: bool = False,
    **kwargs
) -> Union[NeuralClient, NeuralClientMock]:
    """
    Factory function to create a neural client.
    
    Args:
        config_path: Path to configuration file
        mock: Use mock client for testing
        **kwargs: Additional arguments passed to client
        
    Returns:
        NeuralClient or NeuralClientMock instance
    """
    if mock or not NEURAL_SEARCH_AVAILABLE:
        return NeuralClientMock()
    
    return NeuralClient(config_path=config_path, **kwargs)
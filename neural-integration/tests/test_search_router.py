"""Unit tests for SearchRouter."""
import pytest
from datetime import date
from unittest.mock import Mock, patch

from travel_scout.search_router import (
    SearchRouter, UnifiedSearchResponse, SearchResult, search
)


class TestSearchRouterInitialization:
    """Tests for router initialization."""
    
    def test_router_initialization(self):
        """Router should initialize with defaults."""
        router = SearchRouter(auto_register_scrapers=False)
        
        assert router is not None
        assert router.orchestrator is not None
        assert router.config is not None
    
    def test_router_with_custom_config(self):
        """Router should accept custom config path."""
        router = SearchRouter(
            config_path=None,  # Will use defaults
            auto_register_scrapers=False
        )
        
        assert router is not None
    
    def test_router_loads_config(self):
        """Router should load configuration."""
        router = SearchRouter(auto_register_scrapers=False)
        
        # Should have default config values
        assert "primary_search" in router.config or router.config == {}


class TestUnifiedSearch:
    """Tests for unified_search method."""
    
    @pytest.fixture
    def router(self):
        """Create router with mocked orchestrator."""
        router = SearchRouter(auto_register_scrapers=False)
        
        # Mock orchestrator
        mock_result = Mock()
        mock_result.source = Mock(value="neural")
        mock_result.results = []
        mock_result.latency_ms = 100
        mock_result.cached = False
        mock_result.failover_reason = None
        mock_result.metrics = None
        mock_result.to_dict.return_value = {
            "source": "neural",
            "results": [],
            "latency_ms": 100
        }
        
        router.orchestrator.search = Mock(return_value=mock_result)
        
        return router
    
    def test_basic_search(self, router):
        """Basic search should return response."""
        result = router.unified_search("flights to London")
        
        assert isinstance(result, UnifiedSearchResponse)
        assert result.query == "flights to London"
    
    def test_search_with_location(self, router):
        """Search should accept location parameter."""
        result = router.unified_search(
            "hotels",
            location="Paris"
        )
        
        assert result.query == "hotels"
        # Location is passed to orchestrator
        call_kwargs = router.orchestrator.search.call_args[1]
        assert call_kwargs.get('location') == "Paris"
    
    def test_search_with_date_range(self, router):
        """Search should accept date range."""
        date_from = date(2026, 6, 1)
        date_to = date(2026, 6, 7)
        
        result = router.unified_search(
            "flights to London",
            date_range=(date_from, date_to)
        )
        
        call_kwargs = router.orchestrator.search.call_args[1]
        assert call_kwargs.get('date_range') == (date_from, date_to)
    
    def test_search_with_filters(self, router):
        """Search should apply filters to results."""
        # Set up mock to return results that can be filtered
        mock_result = Mock()
        mock_result.source = Mock(value="neural")
        mock_result.results = [
            {"id": "1", "title": "Cheap Flight", "price": 100, "url": "http://test.com"},
            {"id": "2", "title": "Expensive Flight", "price": 1000, "url": "http://test2.com"},
        ]
        mock_result.latency_ms = 100
        mock_result.cached = False
        mock_result.failover_reason = None
        mock_result.metrics = None
        
        router.orchestrator.search = Mock(return_value=mock_result)
        
        result = router.unified_search(
            "flights",
            filters={"max_price": 500}
        )
        
        # Should filter out expensive flight
        assert len(result.results) == 1
        assert result.results[0].price == 100
    
    def test_empty_query(self, router):
        """Empty query should return empty response."""
        result = router.unified_search("")
        
        assert result.total_results == 0
        assert len(result.results) == 0
    
    def test_search_limits_results(self, router):
        """Should respect result limit."""
        # Create mock with many results
        mock_result = Mock()
        mock_result.source = Mock(value="neural")
        mock_result.results = [{"id": f"{i}", "title": f"Result {i}", "url": f"http://test{i}.com"} for i in range(20)]
        mock_result.latency_ms = 100
        mock_result.cached = False
        mock_result.failover_reason = None
        mock_result.metrics = None
        
        router.orchestrator.search = Mock(return_value=mock_result)
        
        result = router.unified_search("test", limit=5)
        
        assert result.total_results == 5
        assert len(result.results) == 5


class TestSpecializedSearches:
    """Tests for specialized search methods."""
    
    @pytest.fixture
    def router(self):
        """Create router with mocked orchestrator."""
        router = SearchRouter(auto_register_scrapers=False)
        
        mock_result = Mock()
        mock_result.source = Mock(value="neural")
        mock_result.results = []
        mock_result.latency_ms = 100
        mock_result.cached = False
        mock_result.failover_reason = None
        mock_result.metrics = None
        mock_result.to_dict.return_value = {"source": "neural", "results": []}
        
        router.orchestrator.search = Mock(return_value=mock_result)
        
        return router
    
    def test_search_flights(self, router):
        """Flight search should set correct search_type."""
        result = router.search_flights(
            origin="MPM",
            destination="LHR",
            depart_date=date(2026, 6, 1)
        )
        
        call_kwargs = router.orchestrator.search.call_args[1]
        assert call_kwargs.get('search_type') == "flights"
    
    def test_search_hotels(self, router):
        """Hotel search should set correct search_type."""
        result = router.search_hotels(
            location="Paris",
            check_in=date(2026, 6, 1),
            check_out=date(2026, 6, 5)
        )
        
        call_kwargs = router.orchestrator.search.call_args[1]
        assert call_kwargs.get('search_type') == "hotels"
        assert call_kwargs.get('location') == "Paris"
    
    def test_search_events(self, router):
        """Event search should set correct search_type."""
        result = router.search_events(
            location="New York",
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 31)
        )
        
        call_kwargs = router.orchestrator.search.call_args[1]
        assert call_kwargs.get('search_type') == "events"


class TestResultConversion:
    """Tests for result format conversion."""
    
    def test_orchestrated_to_unified_conversion(self):
        """Should convert orchestrated results correctly."""
        router = SearchRouter(auto_register_scrapers=False)
        
        # Create mock orchestrated result
        mock_orchestrated = Mock()
        mock_orchestrated.source = Mock(value="neural")
        mock_orchestrated.results = [
            {
                "id": "1",
                "title": "Test Result",
                "description": "Test description",
                "url": "http://test.com",
                "source": "test_source",
                "price": 100,
                "currency": "USD",
                "location": "London",
                "relevance_score": 0.85,
                "extra_field": "value"
            }
        ]
        mock_orchestrated.latency_ms = 150
        mock_orchestrated.cached = False
        mock_orchestrated.failover_reason = Mock(value="none")
        mock_orchestrated.metrics = Mock(to_dict=lambda: {"some": "metric"})
        mock_orchestrated.metadata = {}
        
        result = router._convert_to_unified_response(
            mock_orchestrated,
            "test query",
            "flights"
        )
        
        assert isinstance(result, UnifiedSearchResponse)
        assert len(result.results) == 1
        
        first_result = result.results[0]
        assert isinstance(first_result, SearchResult)
        assert first_result.id == "1"
        assert first_result.title == "Test Result"
        assert first_result.price == 100
        assert first_result.metadata.get("extra_field") == "value"


class TestHistoryTracking:
    """Tests for search history tracking."""
    
    def test_search_added_to_history(self):
        """Search should be added to history."""
        router = SearchRouter(auto_register_scrapers=False)
        
        # Mock orchestrator
        mock_result = Mock()
        mock_result.source = Mock(value="neural")
        mock_result.results = []
        mock_result.latency_ms = 100
        mock_result.cached = False
        mock_result.failover_reason = None
        mock_result.metrics = None
        
        router.orchestrator.search = Mock(return_value=mock_result)
        
        # Perform search
        router.unified_search("test query 1")
        router.unified_search("test query 2")
        
        # Check history
        history = router.get_search_history(limit=10)
        assert len(history) == 2
    
    def test_history_respects_limit(self):
        """History should respect limit parameter."""
        router = SearchRouter(auto_register_scrapers=False)
        
        mock_result = Mock()
        mock_result.source = Mock(value="neural")
        mock_result.results = []
        mock_result.latency_ms = 100
        mock_result.cached = False
        mock_result.failover_reason = None
        mock_result.metrics = None
        
        router.orchestrator.search = Mock(return_value=mock_result)
        
        # Add many searches
        for i in range(10):
            router.unified_search(f"query {i}")
        
        # Get limited history
        history = router.get_search_history(limit=5)
        assert len(history) == 5


class TestModuleLevelSearch:
    """Tests for module-level search function."""
    
    def test_module_search_creates_router(self):
        """Module-level search should create router."""
        with patch('travel_scout.search_router.SearchRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.unified_search.return_value = Mock(total_results=0)
            mock_router_class.return_value = mock_router
            
            result = search("test query")
            
            mock_router_class.assert_called_once()
            mock_router.unified_search.assert_called_once()


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_orchestrator_error_returns_error_response(self):
        """Should return error response on orchestrator failure."""
        router = SearchRouter(auto_register_scrapers=False)
        
        # Make orchestrator raise exception
        router.orchestrator.search = Mock(side_effect=Exception("Test error"))
        
        result = router.unified_search("test query")
        
        assert result.source == "neural"  # Default
        assert len(result.results) == 0
        assert result.metrics is not None
        assert "error" in result.metrics
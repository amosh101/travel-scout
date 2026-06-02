"""Unit tests for SearchOrchestrator."""
import pytest
from unittest.mock import Mock, patch, MagicMock

from travel_scout.search_orchestrator import (
    SearchOrchestrator,
    SearchSource,
    FailoverReason,
    QualityScore,
    OrchestratedResult
)


class TestFailoverLogic:
    """Tests for failover decision logic."""
    
    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with test config."""
        return SearchOrchestrator(mock=True)
    
    def test_insufficient_results_triggers_failover(self, orchestrator):
        """Should failover when neural returns fewer than threshold results."""
        # Mock neural response with 1 result (below threshold of 3)
        mock_response = Mock()
        mock_response.results = [Mock()]
        
        # Mock staleness check to return False
        with patch.object(orchestrator.neural_client, 'is_result_stale', return_value=False):
            reason = orchestrator._should_failover(mock_response)
        
        assert reason == FailoverReason.INSUFFICIENT_RESULTS
    
    def test_sufficient_results_no_failover(self, orchestrator):
        """Should not failover with adequate results."""
        mock_response = Mock()
        mock_response.results = [Mock() for _ in range(5)]  # 5 results
        
        with patch.object(orchestrator.neural_client, 'is_result_stale', return_value=False):
            reason = orchestrator._should_failover(mock_response)
        
        assert reason == FailoverReason.NONE
    
    def test_neural_unavailable_triggers_failover(self, orchestrator):
        """Should failover when neural is unavailable."""
        reason = orchestrator._should_failover(None)
        
        assert reason == FailoverReason.NEURAL_UNAVAILABLE
    
    def test_stale_results_trigger_failover(self, orchestrator):
        """Should failover when most results are stale."""
        mock_response = Mock()
        mock_response.results = [Mock() for _ in range(5)]
        
        # Make all results stale
        with patch.object(orchestrator.neural_client, 'is_result_stale', return_value=True):
            reason = orchestrator._should_failover(mock_response)
        
        assert reason == FailoverReason.STALE_RESULTS


class TestLiveDataKeywords:
    """Tests for live data keyword detection."""
    
    def test_live_price_keyword(self):
        """Should detect 'live price' keyword."""
        orchestrator = SearchOrchestrator(mock=True)
        
        queries = [
            "live price flights to London",
            "what's the live price for hotels in Paris",
            "show live prices"
        ]
        
        for query in queries:
            reason = orchestrator._check_live_data_keywords(query)
            assert reason == FailoverReason.LIVE_DATA_REQUESTED, f"Failed for: {query}"
    
    def test_current_availability_keyword(self):
        """Should detect 'current availability' keyword."""
        orchestrator = SearchOrchestrator(mock=True)
        
        reason = orchestrator._check_live_data_keywords(
            "current availability for events in New York"
        )
        
        assert reason == FailoverReason.LIVE_DATA_REQUESTED
    
    def test_real_time_keyword(self):
        """Should detect 'real-time' keyword variations."""
        orchestrator = SearchOrchestrator(mock=True)
        
        queries = [
            "real-time flight status",
            "real time prices",
            "realtime availability"
        ]
        
        for query in queries:
            reason = orchestrator._check_live_data_keywords(query)
            assert reason == FailoverReason.LIVE_DATA_REQUESTED, f"Failed for: {query}"
    
    def test_normal_query_no_live_data(self):
        """Normal queries should not trigger live data failover."""
        orchestrator = SearchOrchestrator(mock=True)
        
        queries = [
            "flights to London",
            "hotels in Paris",
            "what's the weather like",
            "cheap restaurants"
        ]
        
        for query in queries:
            reason = orchestrator._check_live_data_keywords(query)
            assert reason == FailoverReason.NONE, f"Failed for: {query}"


class TestQualityScoring:
    """Tests for result quality metrics."""
    
    def test_quality_score_calculation(self):
        """Should calculate quality metrics."""
        orchestrator = SearchOrchestrator(mock=True)
        
        results = [
            {"title": "Test 1", "url": "http://test1.com", "relevance_score": 0.8},
            {"title": "Test 2", "url": "http://test2.com", "relevance_score": 0.7},
            {"title": "Test 3", "url": "http://test3.com", "relevance_score": 0.9},
        ]
        
        quality = orchestrator._calculate_quality_score(
            results, SearchSource.NEURAL
        )
        
        assert isinstance(quality, QualityScore)
        assert 0 <= quality.overall <= 1
        assert 0 <= quality.relevance <= 1
        assert 0 <= quality.freshness <= 1
        assert 0 <= quality.completeness <= 1
        assert 0 <= quality.diversity <= 1
    
    def test_empty_results_quality(self):
        """Empty results should have zero quality."""
        orchestrator = SearchOrchestrator(mock=True)
        
        quality = orchestrator._calculate_quality_score([], SearchSource.NEURAL)
        
        assert quality.overall == 0
        assert quality.relevance == 0


class TestScraperRegistration:
    """Tests for scraper callback registration."""
    
    def test_register_scraper(self):
        """Should register scraper callback."""
        orchestrator = SearchOrchestrator(mock=True)
        mock_scraper = Mock(return_value=[])
        
        orchestrator.register_scraper("flights", mock_scraper)
        
        assert "flights" in orchestrator.scraper_callbacks
        assert orchestrator.scraper_callbacks["flights"] == mock_scraper
    
    def test_register_multiple_scrapers(self):
        """Should register multiple scrapers."""
        orchestrator = SearchOrchestrator(mock=True)
        
        orchestrator.register_scraper("flights", Mock())
        orchestrator.register_scraper("hotels", Mock())
        orchestrator.register_scraper("events", Mock())
        
        assert len(orchestrator.scraper_callbacks) == 3
    
    def test_scraper_called_with_correct_args(self):
        """Scraper should receive correct arguments."""
        orchestrator = SearchOrchestrator(mock=True)
        mock_scraper = Mock(return_value=[{"title": "Result"}])
        
        orchestrator.register_scraper("flights", mock_scraper)
        
        # Call orchestrator
        with patch.object(orchestrator, '_should_failover', return_value=FailoverReason.INSUFFICIENT_RESULTS):
            orchestrator.search(
                "flights to London",
                location="Maputo",
                search_type="flights"
            )
        
        # Verify scraper called
        mock_scraper.assert_called_once()
        call_kwargs = mock_scraper.call_args[1]
        assert call_kwargs.get('query') == "flights to London"
        assert call_kwargs.get('location') == "Maputo"


class TestResultMerging:
    """Tests for result merging in hybrid mode."""
    
    def test_merge_results_no_duplicates(self):
        """Should not include duplicate URLs."""
        orchestrator = SearchOrchestrator(mock=True)
        
        neural_results = Mock()
        neural_results.results = [
            Mock(
                id="n1",
                text="Neural result 1",
                metadata={"url": "http://example.com/1"},
                source_type="neural",
                collection="web",
                similarity=0.9
            )
        ]
        
        scraper_results = [
            {"title": "Scraper 1", "url": "http://example.com/1"},  # Duplicate
            {"title": "Scraper 2", "url": "http://example.com/2"}   # New
        ]
        
        merged = orchestrator._merge_results(neural_results, scraper_results)
        
        # Should have 2 unique URLs
        urls = [r.get('url') for r in merged]
        assert len(urls) == len(set(urls))  # No duplicates
    
    def test_merge_preserves_neural_order(self):
        """Neural results should come first in hybrid mode."""
        orchestrator = SearchOrchestrator(mock=True)
        
        neural_results = Mock()
        neural_results.results = [
            Mock(id="n1", text="text1", metadata={"url": "http://neural.com"},
                 source_type="neural", collection="web", similarity=0.9)
        ]
        
        scraper_results = [
            {"title": "Scraper", "url": "http://scraper.com"}
        ]
        
        merged = orchestrator._merge_results(neural_results, scraper_results)
        
        # First result should be from neural
        assert "neural" in str(merged[0]) or "http://neural.com" in str(merged[0])


class TestMetricsCollection:
    """Tests for metrics collection."""
    
    def test_metrics_added_to_history(self):
        """Should add metrics to history after search."""
        orchestrator = SearchOrchestrator(mock=True)
        
        with patch.object(orchestrator, '_search_neural', return_value=(Mock(), 100)):
            with patch.object(orchestrator, '_should_failover', return_value=FailoverReason.NONE):
                orchestrator.search("test query")
        
        assert len(orchestrator.metrics_history) > 0
    
    def test_metrics_summary(self):
        """Should provide summary of recent metrics."""
        orchestrator = SearchOrchestrator(mock=True)
        
        # Add some metrics
        orchestrator.metrics_history = [
            Mock(query="q1", source=SearchSource.NEURAL, latency_ms=100,
                 neural_result_count=5, scraper_result_count=0),
            Mock(query="q2", source=SearchSource.SCRAPER, latency_ms=2000,
                 neural_result_count=0, scraper_result_count=10),
        ]
        
        summary = orchestrator.get_metrics_summary(days=7)
        
        assert "total_searches" in summary
        assert summary["total_searches"] == 2


class TestOrchestratorSearch:
    """Integration tests for orchestrator search method."""
    
    def test_basic_search(self):
        """Basic search should complete."""
        orchestrator = SearchOrchestrator(mock=True)
        
        with patch.object(orchestrator, '_search_neural', return_value=(Mock(), 100)):
            with patch.object(orchestrator, '_should_failover', return_value=FailoverReason.NONE):
                result = orchestrator.search("flights to London")
        
        assert isinstance(result, OrchestratedResult)
        assert result.query == "flights to London"
    
    def test_search_returns_metadata(self):
        """Search should include metadata."""
        orchestrator = SearchOrchestrator(mock=True)
        
        with patch.object(orchestrator, '_search_neural', return_value=(Mock(), 100)):
            with patch.object(orchestrator, '_should_failover', return_value=FailoverReason.NONE):
                result = orchestrator.search("test query")
        
        assert "metadata" in result.to_dict()
        assert "metrics" in result.to_dict()
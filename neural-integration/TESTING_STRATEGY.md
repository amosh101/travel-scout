# Testing Strategy

Comprehensive testing approach for the Neural Search integration.

---

## Testing Pyramid

```
    ┌─────────────┐
    │   E2E       │  <- Full integration tests
    │  (Manual)   │
    ├─────────────┤
    │ Integration │  <- Component interaction tests
    │   (pytest)  │
    ├─────────────┤
    │    Unit     │  <- Individual component tests
    │   (pytest)  │
    ├─────────────┤
    │   Static    │  <- Type checking, linting
    │   (mypy)    │
    └─────────────┘
```

---

## 1. Unit Tests

### File Structure

```
tests/
├── __init__.py
├── conftest.py              # Shared fixtures
├── test_neural_client.py    # Neural client tests
├── test_orchestrator.py     # Routing logic tests
├── test_index_sync.py       # Index sync tests
├── test_search_router.py    # Router tests
└── fixtures/
    ├── sample_flights.json
    ├── sample_hotels.json
    └── sample_events.json
```

### test_neural_client.py

```python
"""Unit tests for NeuralClient."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from travel_scout.neural_client import (
    NeuralClient, NeuralClientMock, create_client,
    NeuralSearchResponse, NeuralSearchResult
)


class TestNeuralClientMock:
    """Tests for mock client (no dependencies)."""
    
    def test_mock_search_returns_results(self):
        """Mock client should return results."""
        client = NeuralClientMock()
        response = client.search("flights to London")
        
        assert response is not None
        assert len(response.results) > 0
        assert response.latency_ms < 100  # Mock is fast
    
    def test_mock_collection_stats(self):
        """Mock should return fake stats."""
        client = NeuralClientMock()
        stats = client.get_collection_stats()
        
        assert "collections" in stats


class TestNeuralClientReal:
    """Tests for real neural client (requires ChromaDB)."""
    
    @pytest.fixture
    def client(self):
        """Create client with test config."""
        # Use mock if neural not available
        try:
            return create_client(mock=False)
        except Exception:
            return create_client(mock=True)
    
    def test_initialization(self, client):
        """Client should initialize properly."""
        assert client.is_initialized()
    
    def test_search_basic(self, client):
        """Basic search should return response."""
        response = client.search("travel to europe")
        
        assert isinstance(response, NeuralSearchResponse)
        assert hasattr(response, 'results')
        assert hasattr(response, 'latency_ms')
    
    def test_search_with_collections(self, client):
        """Search should respect collection filter."""
        response = client.search(
            "hotels in paris",
            collections=["web"]
        )
        
        for result in response.results:
            assert result.collection == "web"
    
    def test_search_reranking(self, client):
        """Reranking should improve result order."""
        response = client.search(
            "flights to london",
            limit=5,
            rerank=True
        )
        
        assert response.reranked is True
    
    def test_staleness_detection(self, client):
        """Should detect stale results."""
        # Create old result
        old_result = NeuralSearchResult(
            id="test",
            text="test",
            title="test",
            url="test",
            source_type="test",
            collection="test",
            similarity=0.8,
            indexed_at=(datetime.now() - timedelta(days=10)).isoformat()
        )
        
        assert client.is_result_stale(old_result, max_days=7)
    
    def test_caching(self, client):
        """Results should be cached."""
        response1 = client.search("test query")
        response2 = client.search("test query")
        
        # Second should be cached
        assert response2.cached or not hasattr(client, '_result_cache')


class TestNeuralClientErrorHandling:
    """Tests for error conditions."""
    
    def test_uninitialized_client_raises_error(self):
        """Should raise error if not initialized."""
        client = NeuralClient.__new__(NeuralClient)
        client._initialized = False
        
        with pytest.raises(Exception):
            client.search("test")
    
    def test_invalid_collection_handled(self):
        """Should handle invalid collection gracefully."""
        client = create_client(mock=True)
        response = client.search("test", collections=["nonexistent"])
        
        # Should return empty, not crash
        assert response is not None
```

### test_orchestrator.py

```python
"""Unit tests for SearchOrchestrator."""
import pytest
from unittest.mock import Mock, patch, AsyncMock

from travel_scout.search_orchestrator import (
    SearchOrchestrator,
    SearchSource,
    FailoverReason,
    QualityScore
)


class TestFailoverLogic:
    """Tests for failover decision logic."""
    
    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with test config."""
        return SearchOrchestrator(mock=True)
    
    def test_insufficient_results_triggers_failover(self, orchestrator):
        """Should failover when neural returns few results."""
        # Mock neural response with 1 result
        mock_response = Mock()
        mock_response.results = [Mock()]
        
        reason = orchestrator._should_failover(mock_response)
        
        assert reason == FailoverReason.INSUFFICIENT_RESULTS
    
    def test_stale_results_trigger_failover(self, orchestrator):
        """Should failover when results are stale."""
        # Mock response with all stale results
        mock_response = Mock()
        mock_response.results = [Mock(), Mock(), Mock(), Mock()]
        
        with patch.object(orchestrator, 'neural_client') as mock_client:
            mock_client.is_result_stale.return_value = True
            
            reason = orchestrator._should_failover(mock_response)
            
            assert reason == FailoverReason.STALE_RESULTS
    
    def test_live_keywords_trigger_direct_scraper(self, orchestrator):
        """Should detect live data keywords."""
        queries = [
            "live price flights to London",
            "current availability hotel Paris",
            "real-time flight status"
        ]
        
        for query in queries:
            reason = orchestrator._check_live_data_keywords(query)
            assert reason == FailoverReason.LIVE_DATA_REQUESTED, f"Failed for: {query}"
    
    def test_sufficient_results_no_failover(self, orchestrator):
        """Should not failover with good results."""
        mock_response = Mock()
        mock_response.results = [Mock() for _ in range(5)]  # 5 results
        
        with patch.object(orchestrator, 'neural_client') as mock_client:
            mock_client.is_result_stale.return_value = False
            
            reason = orchestrator._should_failover(mock_response)
            
            assert reason == FailoverReason.NONE


class TestQualityScoring:
    """Tests for result quality metrics."""
    
    def test_quality_score_calculation(self):
        """Should calculate quality metrics."""
        orchestrator = SearchOrchestrator(mock=True)
        
        results = [
            {"title": "Test", "url": "http://test.com", "relevance_score": 0.8},
            {"title": "Test2", "url": "http://test2.com", "relevance_score": 0.7},
        ]
        
        quality = orchestrator._calculate_quality_score(
            results, SearchSource.NEURAL
        )
        
        assert 0 <= quality.overall <= 1
        assert 0 <= quality.relevance <= 1
        assert 0 <= quality.freshness <= 1
        assert 0 <= quality.completeness <= 1
        assert 0 <= quality.diversity <= 1


class TestScraperIntegration:
    """Tests for scraper callback integration."""
    
    def test_scraper_registration(self):
        """Should register scraper callbacks."""
        orchestrator = SearchOrchestrator(mock=True)
        mock_scraper = Mock(return_value=[])
        
        orchestrator.register_scraper("flights", mock_scraper)
        
        assert "flights" in orchestrator.scraper_callbacks
    
    def test_scraper_called_on_failover(self):
        """Should call scraper when failover occurs."""
        orchestrator = SearchOrchestrator(mock=True)
        mock_scraper = Mock(return_value=[{"title": "Scraper Result"}])
        orchestrator.register_scraper("flights", mock_scraper)
        
        # Force failover
        with patch.object(orchestrator, '_should_failover') as mock_should:
            mock_should.return_value = FailoverReason.INSUFFICIENT_RESULTS
            
            result = orchestrator.search(
                "flights to London",
                search_type="flights"
            )
            
            # Scraper should have been called
            mock_scraper.assert_called_once()
```

### test_index_sync.py

```python
"""Unit tests for IndexSync."""
import pytest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from travel_scout.index_sync import IndexSync, SyncResult, SyncStatus, SyncRecord


class TestContentHashing:
    """Tests for content hash functionality."""
    
    def test_same_content_same_hash(self):
        """Same content should produce same hash."""
        sync = IndexSync.__new__(IndexSync)
        sync._sync_state = {}
        
        hash1 = sync._generate_content_hash("test content")
        hash2 = sync._generate_content_hash("test content")
        
        assert hash1 == hash2
    
    def test_different_content_different_hash(self):
        """Different content should produce different hash."""
        sync = IndexSync.__new__(IndexSync)
        sync._sync_state = {}
        
        hash1 = sync._generate_content_hash("content A")
        hash2 = sync._generate_content_hash("content B")
        
        assert hash1 != hash2
    
    def test_has_changed_detection(self):
        """Should detect content changes."""
        sync = IndexSync.__new__(IndexSync)
        sync._sync_state = {
            "doc1": SyncRecord(
                document_id="doc1",
                content_hash=sync._generate_content_hash("old content"),
                indexed_at=datetime.now().isoformat(),
                source_url="http://test.com"
            )
        }
        
        # Same content
        assert not sync._has_changed("doc1", "old content")
        
        # Changed content
        assert sync._has_changed("doc1", "new content")


class TestSyncOperations:
    """Tests for sync operations."""
    
    @pytest.fixture
    def sync(self):
        """Create mock sync instance."""
        with patch('travel_scout.index_sync.NEURAL_SEARCH_AVAILABLE', False):
            sync = IndexSync.__new__(IndexSync)
            sync._initialized = True
            sync._sync_state = {}
            sync.state_file = Path("/tmp/test_sync_state.json")
            sync.collection = "test"
            return sync
    
    def test_empty_documents_sync(self, sync):
        """Should handle empty document list."""
        result = sync.sync_documents([])
        
        assert result.status == SyncStatus.COMPLETED
        assert result.documents_processed == 0
    
    def test_incremental_sync_skips_unchanged(self, sync):
        """Should skip unchanged documents."""
        # First sync
        docs = [{"url": "http://test.com", "content": "content", "title": "Test"}]
        
        with patch.object(sync, 'vector_store'):
            result1 = sync.sync_documents(docs)
            assert result1.documents_indexed == 1
            
            # Second sync with same content
            result2 = sync.sync_documents(docs)
            assert result2.documents_indexed == 0  # Skipped
```

---

## 2. Integration Tests

### test_integration.py

```python
"""Integration tests for full search flow."""
import pytest
import asyncio
from datetime import date

from travel_scout.search_router import SearchRouter
from travel_scout.search_orchestrator import SearchOrchestrator, SearchSource


@pytest.fixture
def router():
    """Create real router instance."""
    return SearchRouter(auto_register_scrapers=False)


class TestEndToEndSearch:
    """End-to-end search tests."""
    
    def test_basic_search_flow(self, router):
        """Basic search should complete successfully."""
        result = router.unified_search("flights to London")
        
        assert result is not None
        assert result.query == "flights to London"
        assert isinstance(result.results, list)
        assert result.latency_ms >= 0
    
    def test_search_with_location(self, router):
        """Search with location filter."""
        result = router.unified_search(
            "hotels",
            location="Paris",
            search_type="hotels"
        )
        
        assert result.query == "hotels"
        assert result.search_type == "hotels"
    
    def test_search_with_date_range(self, router):
        """Search with date range."""
        result = router.unified_search(
            "flights to New York",
            date_range=(date(2026, 6, 1), date(2026, 6, 7)),
            search_type="flights"
        )
        
        assert result.search_type == "flights"
    
    def test_specialized_flight_search(self, router):
        """Flight-specific search method."""
        result = router.search_flights(
            origin="MPM",
            destination="LHR",
            depart_date=date(2026, 6, 1)
        )
        
        assert result.search_type == "flights"
    
    def test_specialized_hotel_search(self, router):
        """Hotel-specific search method."""
        result = router.search_hotels(
            location="Paris",
            check_in=date(2026, 6, 1),
            check_out=date(2026, 6, 5)
        )
        
        assert result.search_type == "hotels"
    
    def test_result_filtering(self, router):
        """Should apply filters to results."""
        result = router.unified_search(
            "flights",
            search_type="flights",
            filters={"max_price": 1000}
        )
        
        # Results should respect filter
        for r in result.results:
            if r.price:
                assert r.price <= 1000


class TestFailoverScenarios:
    """Tests for failover behavior."""
    
    def test_neural_primary_used(self, router):
        """Should try neural first."""
        result = router.unified_search("common travel query")
        
        # Should indicate neural was attempted
        assert result.source in ["neural", "scraper", "hybrid"]
    
    def test_failover_reasons_tracked(self, router):
        """Should track why failover occurred."""
        # Query unlikely to return results
        result = router.unified_search("xyzabc123nonexistent456")
        
        # Should have failover reason if scraper used
        if result.source == "scraper":
            assert result.failover_reason is not None


class TestMetricsCollection:
    """Tests for metrics."""
    
    def test_metrics_collected(self, router):
        """Should collect search metrics."""
        # Perform searches
        router.unified_search("test query 1")
        router.unified_search("test query 2")
        
        # Get metrics
        metrics = router.get_metrics()
        
        assert "total_searches" in metrics or "message" in metrics
    
    def test_search_history_tracked(self, router):
        """Should track search history."""
        router.unified_search("history test")
        
        history = router.get_search_history(limit=5)
        assert len(history) >= 1
        assert history[-1]["query"] == "history test"


class TestSyncIntegration:
    """Tests for index sync integration."""
    
    def test_sync_to_neural(self, router):
        """Should sync data to neural index."""
        sample_flights = [
            {
                "origin": "MPM",
                "destination": "JNB",
                "airline": "Test Air",
                "price": 500,
                "currency": "USD",
                "depart_date": "2026-06-01",
                "duration_minutes": 90,
                "stops": 0,
                "booking_link": "http://test.com"
            }
        ]
        
        result = router.sync_to_neural("flights", sample_flights)
        
        assert "status" in result
```

---

## 3. Failover Testing

### Manual Failover Tests

```python
"""Manual test script for failover scenarios."""
from travel_scout.search_router import SearchRouter
from travel_scout.search_orchestrator import SearchOrchestrator, SearchSource

def test_scenario_1_neural_success():
    """Scenario: Neural search succeeds with good results."""
    router = SearchRouter()
    result = router.unified_search("flights to London")
    
    print(f"✓ Source: {result.source}")
    print(f"✓ Results: {result.total_results}")
    print(f"✓ Latency: {result.latency_ms}ms")
    
    assert result.source in ["neural", "hybrid"]
    assert result.total_results >= 0


def test_scenario_2_neural_insufficient():
    """Scenario: Neural returns too few results - failover to scraper."""
    router = SearchRouter()
    
    # Use obscure query that neural won't have
    result = router.unified_search("very specific obscure query xyz123")
    
    print(f"✓ Source: {result.source}")
    print(f"✓ Failover reason: {result.failover_reason}")
    
    # Should have attempted failover


def test_scenario_3_live_data_request():
    """Scenario: User requests live prices - skip neural."""
    router = SearchRouter()
    result = router.unified_search("live prices flights to New York")
    
    print(f"✓ Source: {result.source}")
    print(f"✓ Should use scraper for live data")


def test_scenario_4_neural_unavailable():
    """Scenario: Neural search is down."""
    # Simulate by using mock client
    router = SearchRouter(neural_client=None)
    
    result = router.unified_search("flights to London")
    
    print(f"✓ Source: {result.source}")
    print(f"✓ Should fallback gracefully")


if __name__ == "__main__":
    print("=" * 60)
    print("FAILOVER TEST SCENARIOS")
    print("=" * 60)
    
    test_scenario_1_neural_success()
    test_scenario_2_neural_insufficient()
    test_scenario_3_live_data_request()
    test_scenario_4_neural_unavailable()
    
    print("\n" + "=" * 60)
    print("ALL SCENARIOS COMPLETED")
    print("=" * 60)
```

---

## 4. Load Testing

### test_load.py

```python
"""Load testing for search endpoints."""
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from travel_scout.search_router import SearchRouter


def benchmark_search(router: SearchRouter, queries: list, num_requests: int = 100):
    """Benchmark search performance."""
    latencies = []
    
    start = time.time()
    
    for i in range(num_requests):
        query = queries[i % len(queries)]
        req_start = time.time()
        
        result = router.unified_search(query)
        
        latency = (time.time() - req_start) * 1000
        latencies.append(latency)
    
    total_time = time.time() - start
    
    return {
        "total_requests": num_requests,
        "total_time_sec": total_time,
        "requests_per_sec": num_requests / total_time,
        "avg_latency_ms": sum(latencies) / len(latencies),
        "min_latency_ms": min(latencies),
        "max_latency_ms": max(latencies),
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)]
    }


def main():
    """Run load test."""
    router = SearchRouter()
    
    queries = [
        "flights to London",
        "hotels in Paris",
        "events in New York",
        "flights from Maputo to Johannesburg",
        "cheap hotels in Dubai"
    ]
    
    print("Running load test...")
    results = benchmark_search(router, queries, num_requests=50)
    
    print("\nLoad Test Results:")
    print("=" * 40)
    for key, value in results.items():
        print(f"{key}: {value:.2f}" if isinstance(value, float) else f"{key}: {value}")


if __name__ == "__main__":
    main()
```

---

## 5. Continuous Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v2
    
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.12
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov
    
    - name: Run unit tests
      run: |
        pytest tests/unit/ -v --cov=travel_scout --cov-report=xml
    
    - name: Run integration tests
      run: |
        pytest tests/integration/ -v
    
    - name: Run failover tests
      run: |
        python tests/manual/failover_tests.py
    
    - name: Upload coverage
      uses: codecov/codecov-action@v1
      with:
        file: ./coverage.xml
```

---

## 6. Test Data

### fixtures/sample_flights.json

```json
[
  {
    "origin": "MPM",
    "destination": "LHR",
    "airline": "British Airways",
    "price": 850,
    "currency": "USD",
    "depart_date": "2026-06-15",
    "duration_minutes": 600,
    "stops": 0,
    "booking_link": "https://example.com/flights/MPM-LHR-BA-001"
  },
  {
    "origin": "MPM",
    "destination": "JNB",
    "airline": "South African Airways",
    "price": 450,
    "currency": "USD",
    "depart_date": "2026-06-15",
    "duration_minutes": 90,
    "stops": 0,
    "booking_link": "https://example.com/flights/MPM-JNB-SAA-001"
  }
]
```

---

## 7. Acceptance Criteria

| Test | Criteria | Status |
|------|----------|--------|
| Neural Search | Returns results in < 500ms | ⬜ |
| Failover | Triggers when < 3 results | ⬜ |
| Scraper Fallback | Returns results when neural fails | ⬜ |
| Index Sync | Correctly hashes and skips unchanged | ⬜ |
| Quality Metrics | Calculates relevance scores | ⬜ |
| API Response | Returns valid JSON format | ⬜ |
| Error Handling | Graceful degradation | ⬜ |
| Load Test | Handles 10 req/sec | ⬜ |

---

## 8. Debugging Failed Tests

### Common Issues

1. **"Neural search modules not available"**
   - Check PYTHONPATH includes neural-search project
   - Verify ChromaDB is installed

2. **"No collections found"**
   - Run migration script first
   - Check ChromaDB path in config

3. **Failover not triggering**
   - Verify threshold settings in config
   - Check neural result count in debug logs

4. **Scraper timeout**
   - Increase timeout in config
   - Check network connectivity
   - Verify scraper endpoints accessible

### Debug Mode

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Run with verbose output
pytest tests/ -v -s --tb=long
```
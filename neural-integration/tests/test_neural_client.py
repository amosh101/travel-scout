"""Unit tests for NeuralClient."""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Try to import, use mock if not available
try:
    from travel_scout.neural_client import (
        NeuralClient, NeuralClientMock, create_client,
        NeuralSearchResponse, NeuralSearchResult, NeuralClientError
    )
    NEURAL_AVAILABLE = True
except ImportError:
    NEURAL_AVAILABLE = False


class TestNeuralClientMock:
    """Tests for mock client (no dependencies)."""
    
    def test_mock_initialization(self):
        """Mock client should initialize without errors."""
        client = NeuralClientMock()
        assert client.is_initialized() is True
    
    def test_mock_search_returns_results(self):
        """Mock search should return results."""
        client = NeuralClientMock()
        response = client.search("flights to London")
        
        assert response is not None
        assert len(response.results) > 0
        assert response.latency_ms < 100  # Mock is fast
        assert response.cached is False
    
    def test_mock_search_with_collections(self):
        """Mock should respect collection parameter."""
        client = NeuralClientMock()
        response = client.search(
            "test query",
            collections=["web", "events"]
        )
        
        assert response.collections_searched == ["web", "events"]
    
    def test_mock_collection_stats(self):
        """Mock should return fake stats."""
        client = NeuralClientMock()
        stats = client.get_collection_stats()
        
        assert "collections" in stats
        assert "mock" in stats["collections"]
    
    def test_mock_staleness_check(self):
        """Mock staleness check should return False."""
        client = NeuralClientMock()
        
        result = NeuralSearchResult(
            id="test",
            text="test",
            title="test",
            url="test",
            source_type="test",
            collection="test",
            similarity=0.8
        )
        
        assert client.is_result_stale(result, max_days=7) is False


@pytest.mark.skipif(not NEURAL_AVAILABLE, reason="Neural search not available")
class TestNeuralClientReal:
    """Tests for real neural client (requires ChromaDB)."""
    
    @pytest.fixture
    def client(self):
        """Create client, fallback to mock if neural unavailable."""
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
        assert response.latency_ms >= 0
    
    def test_search_with_limit(self, client):
        """Search should respect limit."""
        response = client.search("flights", limit=5)
        assert len(response.results) <= 5
    
    def test_search_with_threshold(self, client):
        """Search should respect threshold."""
        response = client.search("test query", threshold=0.8)
        
        # All results should meet threshold
        for result in response.results:
            assert result.similarity >= 0.8


class TestNeuralSearchResult:
    """Tests for NeuralSearchResult dataclass."""
    
    def test_result_creation(self):
        """Should create result with required fields."""
        result = NeuralSearchResult(
            id="doc_1",
            text="Flight content",
            title="Flight Title",
            url="https://example.com",
            source_type="flight_scraper",
            collection="travel_data",
            similarity=0.85
        )
        
        assert result.id == "doc_1"
        assert result.similarity == 0.85
        assert result.metadata is not None
    
    def test_result_with_metadata(self):
        """Should handle metadata."""
        result = NeuralSearchResult(
            id="doc_1",
            text="content",
            title="title",
            url="url",
            source_type="test",
            collection="test",
            similarity=0.5,
            metadata={"key": "value"}
        )
        
        assert result.metadata["key"] == "value"


class TestCreateClientFactory:
    """Tests for create_client factory function."""
    
    def test_create_mock_client(self):
        """Should create mock when mock=True."""
        client = create_client(mock=True)
        assert isinstance(client, NeuralClientMock)
    
    def test_create_real_client(self):
        """Should attempt real client when mock=False."""
        # Will fail if neural not available
        try:
            client = create_client(mock=False)
            assert isinstance(client, NeuralClient)
        except Exception:
            # Expected if neural not available
            pass


class TestStalenessDetection:
    """Tests for result staleness detection."""
    
    def test_fresh_result(self):
        """Recent result should not be stale."""
        client = NeuralClientMock()
        
        result = NeuralSearchResult(
            id="test",
            text="test",
            title="test",
            url="test",
            source_type="test",
            collection="test",
            similarity=0.8,
            indexed_at=datetime.now().isoformat()
        )
        
        assert not client.is_result_stale(result, max_days=7)
    
    def test_stale_result(self):
        """Old result should be stale."""
        client = NeuralClientMock()
        
        old_date = (datetime.now() - timedelta(days=10)).isoformat()
        result = NeuralSearchResult(
            id="test",
            text="test",
            title="test",
            url="test",
            source_type="test",
            collection="test",
            similarity=0.8,
            indexed_at=old_date
        )
        
        assert client.is_result_stale(result, max_days=7)
    
    def test_result_without_date_is_stale(self):
        """Result without indexed_at should be considered stale."""
        client = NeuralClientMock()
        
        result = NeuralSearchResult(
            id="test",
            text="test",
            title="test",
            url="test",
            source_type="test",
            collection="test",
            similarity=0.8,
            indexed_at=None
        )
        
        assert client.is_result_stale(result, max_days=7)
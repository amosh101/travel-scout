"""Unit tests for IndexSync."""
import pytest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from travel_scout.index_sync import (
    IndexSync, SyncResult, SyncStatus, SyncRecord,
    sync_flights, sync_hotels, sync_events
)


class TestSyncRecord:
    """Tests for SyncRecord dataclass."""
    
    def test_record_creation(self):
        """Should create record with all fields."""
        record = SyncRecord(
            document_id="doc_1",
            content_hash="abc123",
            indexed_at="2026-01-01T00:00:00",
            source_url="http://test.com"
        )
        
        assert record.document_id == "doc_1"
        assert record.content_hash == "abc123"
    
    def test_record_to_dict(self):
        """Should convert to dictionary."""
        record = SyncRecord(
            document_id="doc_1",
            content_hash="abc123",
            indexed_at="2026-01-01T00:00:00",
            source_url="http://test.com"
        )
        
        data = record.to_dict()
        assert data["document_id"] == "doc_1"
        assert data["content_hash"] == "abc123"
    
    def test_record_from_dict(self):
        """Should create from dictionary."""
        data = {
            "document_id": "doc_1",
            "content_hash": "abc123",
            "indexed_at": "2026-01-01T00:00:00",
            "source_url": "http://test.com"
        }
        
        record = SyncRecord.from_dict(data)
        assert record.document_id == "doc_1"


class TestContentHashing:
    """Tests for content hash functionality."""
    
    def test_same_content_same_hash(self):
        """Same content should produce same hash."""
        sync = IndexSync.__new__(IndexSync)
        sync._sync_state = {}
        
        hash1 = sync._generate_content_hash("test content")
        hash2 = sync._generate_content_hash("test content")
        
        assert hash1 == hash2
        assert len(hash1) == 32  # MD5 hex is 32 chars
    
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
        
        # Same content - not changed
        assert not sync._has_changed("doc1", "old content")
        
        # Different content - changed
        assert sync._has_changed("doc1", "new content")
        
        # Unknown document - changed (new)
        assert sync._has_changed("doc2", "content")


class TestSyncOperations:
    """Tests for sync operations."""
    
    @pytest.fixture
    def mock_sync(self, tmp_path):
        """Create mock sync instance."""
        with patch('travel_scout.index_sync.NEURAL_SEARCH_AVAILABLE', False):
            sync = IndexSync.__new__(IndexSync)
            sync._initialized = True
            sync._sync_state = {}
            sync.state_file = tmp_path / "test_sync_state.json"
            sync.collection = "test"
            sync.config = Mock(chunk_size=512, chunk_overlap=50)
            return sync
    
    def test_empty_documents_sync(self, mock_sync):
        """Should handle empty document list."""
        with patch.object(mock_sync, 'vector_store'):
            result = mock_sync.sync_documents([])
        
        assert result.status == SyncStatus.COMPLETED
        assert result.documents_processed == 0
        assert result.documents_indexed == 0
    
    def test_incremental_sync_skips_unchanged(self, mock_sync):
        """Should skip unchanged documents."""
        docs = [
            {"url": "http://test.com", "content": "content", "title": "Test"}
        ]
        
        # First sync
        with patch.object(mock_sync, 'vector_store') as mock_store:
            mock_store.add_documents.return_value = 1
            result1 = mock_sync.sync_documents(docs)
            assert result1.documents_indexed == 1
        
        # Second sync with same content
        with patch.object(mock_sync, 'vector_store') as mock_store:
            mock_store.add_documents.return_value = 0
            result2 = mock_sync.sync_documents(docs)
            assert result2.documents_indexed == 0  # Skipped
    
    def test_sync_tracks_processed_count(self, mock_sync):
        """Should track number of processed documents."""
        docs = [
            {"url": "http://test1.com", "content": "content 1", "title": "Test 1"},
            {"url": "http://test2.com", "content": "content 2", "title": "Test 2"},
        ]
        
        with patch.object(mock_sync, 'vector_store') as mock_store:
            mock_store.add_documents.return_value = 1
            result = mock_sync.sync_documents(docs)
        
        assert result.documents_processed == 2
    
    def test_force_reindex_processes_all(self, mock_sync):
        """Force reindex should process all documents."""
        docs = [
            {"url": "http://test.com", "content": "content", "title": "Test"}
        ]
        
        # Initial sync
        with patch.object(mock_sync, 'vector_store') as mock_store:
            mock_store.add_documents.return_value = 1
            mock_sync.sync_documents(docs)
        
        # Force reindex
        with patch.object(mock_sync, 'vector_store') as mock_store:
            mock_store.add_documents.return_value = 1
            result = mock_sync.sync_documents(docs, force_reindex=True)
            
            # Should be indexed again
            assert result.documents_indexed == 1


class TestSyncFromFile:
    """Tests for file-based syncing."""
    
    def test_sync_from_json_file(self, tmp_path):
        """Should sync from JSON file."""
        # Create test file
        test_file = tmp_path / "test_flights.json"
        test_data = [
            {"url": "http://test.com/1", "content": "Flight 1", "title": "Flight 1"},
            {"url": "http://test.com/2", "content": "Flight 2", "title": "Flight 2"}
        ]
        with open(test_file, 'w') as f:
            json.dump(test_data, f)
        
        # Mock IndexSync
        with patch.object(IndexSync, '__init__', lambda s, **kwargs: None):
            with patch.object(IndexSync, 'sync_documents') as mock_sync:
                mock_sync.return_value = SyncResult(
                    status=SyncStatus.COMPLETED,
                    documents_processed=2,
                    documents_indexed=2,
                    documents_failed=0,
                    errors=[],
                    started_at=datetime.now().isoformat(),
                    collection="test"
                )
                
                sync = IndexSync.__new__(IndexSync)
                sync.collection = "test"
                sync._initialized = True
                
                result = sync.sync_from_json_file(str(test_file))
                
                mock_sync.assert_called_once()


class TestSyncResult:
    """Tests for SyncResult."""
    
    def test_result_to_dict(self):
        """Should convert to dictionary."""
        result = SyncResult(
            status=SyncStatus.COMPLETED,
            documents_processed=10,
            documents_indexed=8,
            documents_failed=2,
            errors=["error 1"],
            started_at="2026-01-01T00:00:00",
            completed_at="2026-01-01T00:01:00",
            collection="flights"
        )
        
        data = result.to_dict()
        
        assert data["status"] == "completed"
        assert data["documents_processed"] == 10
        assert data["documents_indexed"] == 8
        assert data["collection"] == "flights"


class TestSyncHelperFunctions:
    """Tests for sync helper functions."""
    
    def test_sync_flights_converts_to_documents(self):
        """sync_flights should convert FlightOffer data."""
        flights = [
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
        
        # Mock IndexSync
        with patch('travel_scout.index_sync.IndexSync') as MockSync:
            mock_instance = Mock()
            mock_instance.sync_documents.return_value = SyncResult(
                status=SyncStatus.COMPLETED,
                documents_processed=1,
                documents_indexed=1,
                documents_failed=0,
                errors=[],
                started_at=datetime.now().isoformat(),
                collection="travel_data"
            )
            MockSync.return_value = mock_instance
            
            result = sync_flights(flights)
            
            assert MockSync.called
            # Check that sync_documents was called with documents
            call_args = mock_instance.sync_documents.call_args[0][0]
            assert len(call_args) == 1
            assert "MPM" in call_args[0]["content"]
    
    def test_sync_hotels_converts_to_documents(self):
        """sync_hotels should convert hotel data."""
        hotels = [
            {
                "name": "Test Hotel",
                "location": "Paris",
                "price_per_night": 200,
                "rating": 4.5,
                "amenities": ["wifi", "pool"],
                "booking_url": "http://test.com"
            }
        ]
        
        with patch('travel_scout.index_sync.IndexSync') as MockSync:
            mock_instance = Mock()
            mock_instance.sync_documents.return_value = SyncResult(
                status=SyncStatus.COMPLETED,
                documents_processed=1,
                documents_indexed=1,
                documents_failed=0,
                errors=[],
                started_at=datetime.now().isoformat(),
                collection="travel_data"
            )
            MockSync.return_value = mock_instance
            
            result = sync_hotels(hotels)
            
            assert MockSync.called
    
    def test_sync_events_converts_to_documents(self):
        """sync_events should convert event data."""
        events = [
            {
                "name": "Jazz Festival",
                "venue": "Test Venue",
                "city": "Paris",
                "country": "France",
                "date": "2026-07-01",
                "event_type": "concert",
                "url": "http://test.com"
            }
        ]
        
        with patch('travel_scout.index_sync.IndexSync') as MockSync:
            mock_instance = Mock()
            mock_instance.sync_documents.return_value = SyncResult(
                status=SyncStatus.COMPLETED,
                documents_processed=1,
                documents_indexed=1,
                documents_failed=0,
                errors=[],
                started_at=datetime.now().isoformat(),
                collection="travel_data"
            )
            MockSync.return_value = mock_instance
            
            result = sync_events(events)
            
            assert MockSync.called
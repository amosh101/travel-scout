"""
Index Synchronization - Sync Travel Scout scraper data to Neural Search.

Handles automatic indexing of scraper outputs into the neural search system,
supporting incremental updates and scheduled re-indexing.
"""
import sys
import json
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Callable
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum

# Add paths
NEURAL_SEARCH_PATH = Path("/home/ubuntu/.openclaw/workspace/projects/neural-search")
sys.path.insert(0, str(NEURAL_SEARCH_PATH))

try:
    from src.config import NeuralSearchConfig
    from src.embeddings import EmbeddingEngine
    from src.vector_store import VectorStore
    NEURAL_SEARCH_AVAILABLE = True
except ImportError:
    NEURAL_SEARCH_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SyncStatus(Enum):
    """Status of a sync operation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    status: SyncStatus
    documents_processed: int
    documents_indexed: int
    documents_failed: int
    errors: List[str]
    started_at: str
    completed_at: Optional[str] = None
    collection: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "documents_processed": self.documents_processed,
            "documents_indexed": self.documents_indexed,
            "documents_failed": self.documents_failed,
            "errors": self.errors,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "collection": self.collection
        }


@dataclass
class SyncRecord:
    """Record of a previously synced document."""
    document_id: str
    content_hash: str
    indexed_at: str
    source_url: str
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "document_id": self.document_id,
            "content_hash": self.content_hash,
            "indexed_at": self.indexed_at,
            "source_url": self.source_url
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "SyncRecord":
        return cls(**data)


class IndexSyncError(Exception):
    """Base exception for index sync errors."""
    pass


class IndexSync:
    """
    Manages synchronization of scraper data to neural search.
    
    Features:
    - Incremental indexing (only new/changed documents)
    - Content hash tracking to detect changes
    - Batch processing for efficiency
    - Scheduled re-indexing support
    - Multiple source support (files, APIs, databases)
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        db_path: Optional[str] = None,
        collection: str = "travel_data",
        state_file: Optional[str] = None
    ):
        """
        Initialize the index sync manager.
        
        Args:
            config_path: Path to neural search config
            db_path: Override for vector DB path
            collection: Target collection name
            state_file: Path to sync state file
        """
        self.config = None
        self.embedding_engine = None
        self.vector_store = None
        self.collection = collection
        self._initialized = False
        self._sync_history: List[SyncResult] = []
        
        # State tracking for incremental sync
        self.state_file = Path(state_file or "~/.openclaw/travel_scout_sync_state.json")
        self.state_file = self.state_file.expanduser()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._sync_state: Dict[str, SyncRecord] = {}
        self._load_state()
        
        if not NEURAL_SEARCH_AVAILABLE:
            raise IndexSyncError("Neural search modules not available")
        
        try:
            # Load configuration
            self.config = NeuralSearchConfig.from_file(config_path)
            
            if db_path:
                self.config.db_path = db_path
            
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
            logger.info("Index sync initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize index sync: {e}")
            raise IndexSyncError(f"Initialization failed: {e}")
    
    def _load_state(self):
        """Load sync state from file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    self._sync_state = {
                        k: SyncRecord.from_dict(v) for k, v in data.items()
                    }
                logger.info(f"Loaded sync state with {len(self._sync_state)} records")
            except Exception as e:
                logger.warning(f"Failed to load sync state: {e}")
                self._sync_state = {}
    
    def _save_state(self):
        """Save sync state to file."""
        try:
            data = {k: asdict(v) for k, v in self._sync_state.items()}
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save sync state: {e}")
    
    def _generate_content_hash(self, content: str) -> str:
        """Generate hash for content comparison."""
        return hashlib.md5(content.encode()).hexdigest()
    
    def _has_changed(self, document_id: str, content: str) -> bool:
        """Check if document content has changed since last sync."""
        if document_id not in self._sync_state:
            return True
        
        current_hash = self._generate_content_hash(content)
        stored_hash = self._sync_state[document_id].content_hash
        
        return current_hash != stored_hash
    
    def _document_to_chunks(
        self,
        document: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Convert a document to indexable chunks."""
        from src.crawler import chunk_text
        
        content = document.get('content', '')
        if not content:
            return []
        
        # Generate chunks
        chunks = chunk_text(
            content,
            self.config.chunk_size,
            self.config.chunk_overlap
        )
        
        # Add metadata to each chunk
        chunk_docs = []
        for i, chunk_text_content in enumerate(chunks):
            chunk_doc = {
                'url': document.get('url', ''),
                'title': document.get('title', ''),
                'content': chunk_text_content,
                'date': document.get('date', datetime.now().isoformat()),
                'author': document.get('author', ''),
                'source_type': document.get('source_type', 'travel_scout'),
                'chunk_index': i,
                'document_type': document.get('type', 'unknown')
            }
            chunk_docs.append(chunk_doc)
        
        return chunk_docs
    
    def sync_documents(
        self,
        documents: List[Dict[str, Any]],
        force_reindex: bool = False,
        batch_size: int = 100
    ) -> SyncResult:
        """
        Sync documents to neural search index.
        
        Args:
            documents: List of documents to index
            force_reindex: Reindex even if content hasn't changed
            batch_size: Number of documents to process per batch
            
        Returns:
            SyncResult with operation status
        """
        if not self._initialized:
            raise IndexSyncError("Index sync not initialized")
        
        start_time = datetime.now()
        result = SyncResult(
            status=SyncStatus.RUNNING,
            documents_processed=0,
            documents_indexed=0,
            documents_failed=0,
            errors=[],
            started_at=start_time.isoformat(),
            collection=self.collection
        )
        
        try:
            # Filter to only changed documents
            documents_to_index = []
            
            for doc in documents:
                doc_id = doc.get('url') or doc.get('id') or str(hash(str(doc)))
                content = doc.get('content', '')
                
                if force_reindex or self._has_changed(doc_id, content):
                    documents_to_index.append(doc)
                
                result.documents_processed += 1
            
            if not documents_to_index:
                logger.info("No documents to index (all up to date)")
                result.status = SyncStatus.COMPLETED
                result.completed_at = datetime.now().isoformat()
                return result
            
            logger.info(f"Indexing {len(documents_to_index)} documents...")
            
            # Process in batches
            for i in range(0, len(documents_to_index), batch_size):
                batch = documents_to_index[i:i + batch_size]
                
                try:
                    # Index batch
                    count = self.vector_store.add_documents(
                        self.collection,
                        batch,
                        self.config.chunk_size,
                        self.config.chunk_overlap
                    )
                    
                    # Update sync state
                    for doc in batch:
                        doc_id = doc.get('url') or doc.get('id') or str(hash(str(doc)))
                        content = doc.get('content', '')
                        
                        self._sync_state[doc_id] = SyncRecord(
                            document_id=doc_id,
                            content_hash=self._generate_content_hash(content),
                            indexed_at=datetime.now().isoformat(),
                            source_url=doc.get('url', '')
                        )
                    
                    result.documents_indexed += len(batch)
                    logger.debug(f"Indexed batch {i//batch_size + 1}: {count} chunks")
                    
                except Exception as e:
                    error_msg = f"Batch {i//batch_size + 1} failed: {str(e)}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)
                    result.documents_failed += len(batch)
            
            # Save sync state
            self._save_state()
            
            # Determine final status
            if result.documents_failed == 0:
                result.status = SyncStatus.COMPLETED
            elif result.documents_indexed > 0:
                result.status = SyncStatus.PARTIAL
            else:
                result.status = SyncStatus.FAILED
            
            result.completed_at = datetime.now().isoformat()
            self._sync_history.append(result)
            
            logger.info(
                f"Sync complete: {result.documents_indexed} indexed, "
                f"{result.documents_failed} failed"
            )
            
            return result
            
        except Exception as e:
            result.status = SyncStatus.FAILED
            result.errors.append(str(e))
            result.completed_at = datetime.now().isoformat()
            logger.error(f"Sync failed: {e}")
            raise IndexSyncError(f"Sync operation failed: {e}")
    
    def sync_from_json_file(
        self,
        file_path: str,
        **kwargs
    ) -> SyncResult:
        """
        Sync documents from a JSON file.
        
        Args:
            file_path: Path to JSON file containing documents
            **kwargs: Additional arguments passed to sync_documents
            
        Returns:
            SyncResult with operation status
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise IndexSyncError(f"File not found: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                documents = json.load(f)
            
            if not isinstance(documents, list):
                documents = [documents]
            
            logger.info(f"Loaded {len(documents)} documents from {file_path}")
            return self.sync_documents(documents, **kwargs)
            
        except json.JSONDecodeError as e:
            raise IndexSyncError(f"Invalid JSON in {file_path}: {e}")
        except Exception as e:
            raise IndexSyncError(f"Failed to sync from file: {e}")
    
    def sync_from_directory(
        self,
        directory: str,
        pattern: str = "*.json",
        **kwargs
    ) -> List[SyncResult]:
        """
        Sync documents from all JSON files in a directory.
        
        Args:
            directory: Path to directory containing JSON files
            pattern: File pattern to match
            **kwargs: Additional arguments passed to sync_documents
            
        Returns:
            List of SyncResult for each file
        """
        directory = Path(directory)
        
        if not directory.exists():
            raise IndexSyncError(f"Directory not found: {directory}")
        
        results = []
        
        for file_path in directory.glob(pattern):
            try:
                logger.info(f"Syncing from {file_path}")
                result = self.sync_from_json_file(str(file_path), **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync {file_path}: {e}")
                results.append(SyncResult(
                    status=SyncStatus.FAILED,
                    documents_processed=0,
                    documents_indexed=0,
                    documents_failed=0,
                    errors=[str(e)],
                    started_at=datetime.now().isoformat(),
                    completed_at=datetime.now().isoformat(),
                    collection=self.collection
                ))
        
        return results
    
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status and history."""
        return {
            "initialized": self._initialized,
            "collection": self.collection,
            "tracked_documents": len(self._sync_state),
            "last_sync": (
                max(r.started_at for r in self._sync_history)
                if self._sync_history else None
            ),
            "recent_history": [
                r.to_dict() for r in self._sync_history[-5:]
            ]
        }
    
    def clear_sync_state(self):
        """Clear all sync state (forces full reindex on next sync)."""
        self._sync_state.clear()
        self._save_state()
        logger.info("Sync state cleared")
    
    def remove_from_index(self, document_ids: List[str]) -> int:
        """
        Remove documents from the index.
        
        Args:
            document_ids: List of document IDs to remove
            
        Returns:
            Number of documents removed
        """
        if not self._initialized:
            raise IndexSyncError("Index sync not initialized")
        
        try:
            collection = self.vector_store.get_collection(self.collection)
            
            # Get all IDs in collection
            existing = collection.get()
            existing_ids = set(existing['ids'])
            
            # Filter to only existing IDs
            ids_to_remove = [doc_id for doc_id in document_ids if doc_id in existing_ids]
            
            if ids_to_remove:
                collection.delete(ids=ids_to_remove)
                logger.info(f"Removed {len(ids_to_remove)} documents from index")
            
            # Update sync state
            for doc_id in document_ids:
                if doc_id in self._sync_state:
                    del self._sync_state[doc_id]
            
            self._save_state()
            
            return len(ids_to_remove)
            
        except Exception as e:
            logger.error(f"Failed to remove documents: {e}")
            raise IndexSyncError(f"Removal failed: {e}")


# Convenience functions for common operations

def sync_flights(
    flights: List[Dict[str, Any]],
    collection: str = "travel_data",
    **kwargs
) -> SyncResult:
    """
    Sync flight data to neural search.
    
    Args:
        flights: List of flight offers from scrapers
        collection: Target collection
        **kwargs: Additional arguments
        
    Returns:
        SyncResult
    """
    sync = IndexSync(collection=collection)
    
    # Convert FlightOffer objects to documents
    documents = []
    for flight in flights:
        content = (
            f"Flight from {flight.get('origin')} to {flight.get('destination')} "
            f"on {flight.get('depart_date')}. "
            f"Airline: {flight.get('airline')}. "
            f"Price: ${flight.get('price')} {flight.get('currency', 'USD')}. "
            f"Duration: {flight.get('duration_minutes')} minutes. "
            f"Stops: {flight.get('stops')}."
        )
        
        doc = {
            'url': flight.get('booking_link', ''),
            'title': f"{flight.get('airline')} - {flight.get('origin')} to {flight.get('destination')}",
            'content': content,
            'date': flight.get('depart_date', datetime.now().isoformat()),
            'source_type': 'flight_scraper',
            'type': 'flight'
        }
        documents.append(doc)
    
    return sync.sync_documents(documents, **kwargs)


def sync_hotels(
    hotels: List[Dict[str, Any]],
    collection: str = "travel_data",
    **kwargs
) -> SyncResult:
    """
    Sync hotel data to neural search.
    
    Args:
        hotels: List of hotel data from scrapers
        collection: Target collection
        **kwargs: Additional arguments
        
    Returns:
        SyncResult
    """
    sync = IndexSync(collection=collection)
    
    documents = []
    for hotel in hotels:
        content = (
            f"Hotel: {hotel.get('name')} in {hotel.get('location')}. "
            f"Rating: {hotel.get('rating')}. "
            f"Price: ${hotel.get('price_per_night')} per night. "
            f"Amenities: {', '.join(hotel.get('amenities', []))}."
        )
        
        doc = {
            'url': hotel.get('booking_url', ''),
            'title': hotel.get('name', ''),
            'content': content,
            'date': datetime.now().isoformat(),
            'source_type': 'hotel_scraper',
            'type': 'hotel'
        }
        documents.append(doc)
    
    return sync.sync_documents(documents, **kwargs)


def sync_events(
    events: List[Dict[str, Any]],
    collection: str = "travel_data",
    **kwargs
) -> SyncResult:
    """
    Sync event data to neural search.
    
    Args:
        events: List of event data from scrapers
        collection: Target collection
        **kwargs: Additional arguments
        
    Returns:
        SyncResult
    """
    sync = IndexSync(collection=collection)
    
    documents = []
    for event in events:
        content = (
            f"Event: {event.get('name')} at {event.get('venue')}. "
            f"Date: {event.get('date')}. "
            f"Location: {event.get('city', '')}, {event.get('country', '')}. "
            f"Type: {event.get('event_type', 'event')}. "
            f"Price: {event.get('price_range', 'varies')}."
        )
        
        doc = {
            'url': event.get('url', ''),
            'title': event.get('name', ''),
            'content': content,
            'date': event.get('date', datetime.now().isoformat()),
            'source_type': 'event_scraper',
            'type': 'event'
        }
        documents.append(doc)
    
    return sync.sync_documents(documents, **kwargs)
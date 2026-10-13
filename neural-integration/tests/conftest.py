"""
Pytest configuration and shared fixtures.
"""
import pytest
import json
from pathlib import Path
from datetime import datetime

# Add project to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_config():
    """Sample search configuration."""
    return {
        "primary_search": "neural",
        "fallback_enabled": True,
        "neural_threshold": 3,
        "staleness_days": 7,
        "collections": ["web", "events", "travel_data"],
        "cache_enabled": True
    }


@pytest.fixture
def sample_flight_docs():
    """Sample flight documents for testing."""
    return [
        {
            "url": "https://example.com/flights/BA001",
            "title": "British Airways: MPM to LHR",
            "content": "Flight from Maputo to London Heathrow. Price: $850. Duration: 10 hours. Non-stop flight with British Airways.",
            "date": "2026-06-15",
            "source_type": "flight_scraper",
            "type": "flight"
        },
        {
            "url": "https://example.com/flights/SA002",
            "title": "South African Airways: MPM to JNB",
            "content": "Flight from Maputo to Johannesburg. Price: $450. Duration: 1.5 hours. Quick regional flight.",
            "date": "2026-06-15",
            "source_type": "flight_scraper",
            "type": "flight"
        }
    ]


@pytest.fixture
def sample_hotel_docs():
    """Sample hotel documents for testing."""
    return [
        {
            "url": "https://example.com/hotels/paris-hilton",
            "title": "Hilton Paris Opera",
            "content": "Luxury hotel in central Paris. Price: $250 per night. Rating: 4.5 stars. Amenities: spa, restaurant, gym.",
            "date": datetime.now().isoformat(),
            "source_type": "hotel_scraper",
            "type": "hotel"
        }
    ]


@pytest.fixture
def sample_event_docs():
    """Sample event documents for testing."""
    return [
        {
            "url": "https://example.com/events/concert-001",
            "title": "Jazz Festival Paris",
            "content": "Annual jazz festival in Paris featuring international artists. Date: July 15-17, 2026. Location: Parc de la Villette. Price: $50-150.",
            "date": "2026-07-15",
            "source_type": "event_scraper",
            "type": "event"
        }
    ]


@pytest.fixture
def mock_neural_response():
    """Mock neural search response."""
    return {
        "query": "flights to London",
        "results": [
            {
                "id": "doc_1",
                "text": "British Airways flight to London",
                "metadata": {
                    "title": "BA Flight",
                    "url": "https://example.com/ba",
                    "source_type": "web",
                    "indexed_at": datetime.now().isoformat()
                },
                "similarity": 0.85,
                "collection": "web"
            }
        ],
        "latency_ms": 150,
        "result_count": 1,
        "collections_searched": ["web", "travel_data"],
        "timestamp": datetime.now().isoformat(),
        "cached": False,
        "reranked": False
    }


@pytest.fixture
def temp_state_file(tmp_path):
    """Create temporary state file for testing."""
    return tmp_path / "test_sync_state.json"
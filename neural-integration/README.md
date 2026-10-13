# Travel Scout Neural Search Integration

Intelligent search routing between Neural Search (semantic) and legacy scrapers (live data).

## Overview

This integration provides a unified search interface that:
- **Prioritizes Neural Search**: Fast, semantic, local search
- **Automatically Falls Back**: To scrapers when data is stale or missing
- **Tracks Quality Metrics**: Monitors performance and result quality
- **Syncs Data**: Indexes scraper outputs for future neural searches

## Architecture

```
User Query → SearchRouter → SearchOrchestrator
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
              NeuralClient             Scrapers
                    │                       │
                    ▼                       ▼
            Neural Search DB          Live APIs
            (ChromaDB)                 (Web)
```

## Quick Start

### Installation

```bash
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout

# Copy integration files
cp -r neural-integration/travel_scout backend/app/

# Install dependencies
pip install -r neural-integration/requirements.txt
```

### Basic Usage

```python
from travel_scout import SearchRouter

# Create router
router = SearchRouter()

# Search
results = router.unified_search(
    query="flights to London",
    location="Maputo",
    search_type="flights"
)

# Display results
print(f"Found {results.total_results} results from {results.source}")
for r in results.results:
    print(f"  {r.title}: ${r.price}")
```

### Specialized Searches

```python
# Flight search
flights = router.search_flights(
    origin="MPM",
    destination="LHR",
    depart_date=date(2026, 6, 15)
)

# Hotel search
hotels = router.search_hotels(
    location="Paris",
    check_in=date(2026, 7, 1),
    check_out=date(2026, 7, 5)
)

# Event search
events = router.search_events(
    location="New York",
    date_from=date(2026, 8, 1),
    date_to=date(2026, 8, 31)
)
```

## Components

### SearchRouter (`search_router.py`)
Main entry point for search operations.

**Key Methods:**
- `unified_search()` - General search with auto-routing
- `search_flights()` - Flight-specific search
- `search_hotels()` - Hotel-specific search
- `search_events()` - Event-specific search
- `sync_to_neural()` - Index data to neural search

### SearchOrchestrator (`search_orchestrator.py`)
Handles routing logic and failover.

**Failover Triggers:**
- `< neural_threshold` results from neural
- Results are `> staleness_days` old
- User requests "live prices"
- Neural search unavailable

### NeuralClient (`neural_client.py`)
Wrapper for neural search system.

**Features:**
- Semantic search with embeddings
- Cross-encoder reranking
- Result caching
- Staleness detection

### IndexSync (`index_sync.py`)
Synchronizes scraper data to neural index.

**Features:**
- Incremental indexing (content hash tracking)
- Batch processing
- Scheduled sync support

## Configuration

See `travel_scout/config/search_config.json`:

```json
{
  "primary_search": "neural",
  "fallback_enabled": true,
  "neural_threshold": 3,
  "staleness_days": 7,
  "collections": ["web", "events", "travel_data"],
  "auto_index": true
}
```

## Testing

```bash
# Run all tests
cd neural-integration
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_orchestrator.py -v

# Run with coverage
python -m pytest tests/ --cov=travel_scout --cov-report=html
```

## Examples

See `examples.py` for comprehensive usage examples:

```bash
python examples.py
```

## Documentation

- [INTEGRATION_PLAN.md](./INTEGRATION_PLAN.md) - Architecture overview
- [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) - Step-by-step implementation
- [TESTING_STRATEGY.md](./TESTING_STRATEGY.md) - Testing approach

## Performance

| Operation | Latency |
|-----------|---------|
| Neural Search | 50-200ms |
| Scraper Fallback | 2-10s |
| Hybrid (Both) | 3-12s |

## Troubleshooting

### "Neural search modules not available"
Check PYTHONPATH includes neural-search project:
```bash
export PYTHONPATH="/home/ubuntu/.openclaw/workspace/projects/neural-search:$PYTHONPATH"
```

### "No collections found"
Run migration to index sample data:
```bash
cd backend
python scripts/migrate_to_neural.py
```

### Failover too aggressive
Adjust thresholds in config:
```json
{
  "neural_threshold": 1,
  "staleness_days": 14
}
```

## License

MIT License - See main project license.
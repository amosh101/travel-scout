# Travel Scout Neural Search Integration Plan

## Executive Summary

This document outlines the architecture for integrating the **Neural Search System** as the primary search engine for Travel Scout, with automatic failover to existing legacy scrapers. The integration enables semantic search capabilities while maintaining access to live data when needed.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      Travel Scout Bot                          │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │   SearchRouter       │  ← Main API Interface
            │   (search_router.py) │
            └──────────┬───────────┘
                       │
           ┌───────────┴───────────┐
           │                       │
           ▼                       ▼
┌────────────────────┐   ┌──────────────────────┐
│ SearchOrchestrator │   │    IndexSync         │
│ (Routing Logic)    │   │ (Data Sync)          │
└──────────┬───────────┘   └──────────┬───────────┘
           │                        │
           ▼                        ▼
┌────────────────────┐   ┌──────────────────────┐
│ NeuralClient       │   │ Neural Indexer       │
│ (Search Wrapper)   │   │ (neural_index.py)    │
└──────────┬───────────┘   └──────────┬───────────┘
           │                        │
           ▼                        ▼
┌────────────────────┐   ┌──────────────────────┐
│ Neural Search      │◄──┤ Travel Data          │
│ System             │   │ (Scraper Outputs)    │
│ (ChromaDB)         │   │                      │
└──────────┬───────────┘   └──────────────────────┘
           │
           │  Failover
           ▼
┌────────────────────┐
│ Legacy Scrapers    │
│ (Flights, Hotels,  │
│ Events)            │
└────────────────────┘
```

---

## Component Breakdown

### 1. SearchRouter (`search_router.py`)

**Purpose:** Main entry point for all search operations.

**Key Features:**
- Unified `unified_search()` API
- Specialized methods: `search_flights()`, `search_hotels()`, `search_events()`
- Result filtering and formatting
- Metrics collection

**API Design:**
```python
unified_search(
    query: str,
    location: Optional[str] = None,
    date_range: Optional[tuple] = None,
    search_type: str = "auto",  # flights, hotels, events, auto
    filters: Optional[Dict] = None,
    limit: int = 20
) -> UnifiedSearchResponse
```

**Response Format:**
```json
{
  "source": "neural|scraper|hybrid",
  "results": [...],
  "latency_ms": 245,
  "cached": false,
  "query": "flights to London",
  "search_type": "flights",
  "failover_reason": "insufficient_results",
  "metrics": {...},
  "timestamp": "2026-04-27T09:23:00",
  "total_results": 15
}
```

---

### 2. SearchOrchestrator (`search_orchestrator.py`)

**Purpose:** Intelligent routing logic with automatic failover.

**Routing Logic:**

1. **Primary Path:** Neural Search
   - Fast semantic search on indexed data
   - Returns results in ~50-200ms
   - Supports cross-collection querying

2. **Failover Triggers:**
   | Condition | Trigger | Action |
   |-----------|---------|--------|
   | Results < threshold | `result_count < neural_threshold` | Failover to scrapers |
   | Stale data | `staleness > staleness_days` | Failover to scrapers |
   | Missing entity | Specific venue/artist not found | Failover to scrapers |
   | Live data requested | Keywords like "live price" | Go directly to scrapers |
   | Neural unavailable | Connection/embedding failure | Failover to scrapers |

3. **Failover Thresholds:**
   ```json
   {
     "neural_threshold": 3,      // Minimum results from neural
     "staleness_days": 7,        // Max age for neural results
     "fallback_enabled": true    // Allow scraper fallback
   }
   ```

**Metrics Tracked:**
- Query latency (total, neural, scraper)
- Result counts (neural, scraper)
- Quality scores (relevance, freshness, completeness, diversity)
- Failover reasons

---

### 3. NeuralClient (`neural_client.py`)

**Purpose:** Python wrapper for the Neural Search System.

**Capabilities:**
- Semantic search across collections
- Cross-encoder reranking
- Result caching
- Staleness detection
- Collection management

**Configuration:**
```json
{
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "db_path": "~/.openclaw/neural_search_db",
  "default_limit": 10,
  "default_threshold": 0.3
}
```

**Collections Used:**
- `web`: General web content (venues, attractions)
- `events`: Event listings and concerts
- `travel_data`: Travel Scout scraper outputs

---

### 4. IndexSync (`index_sync.py`)

**Purpose:** Synchronize scraper data to neural search index.

**Features:**
- Incremental indexing (only new/changed documents)
- Content hash tracking
- Batch processing (100 docs/batch)
- Scheduled sync support
- Multi-source support (flights, hotels, events)

**Sync Flow:**
```
Scraper Output
     │
     ▼
┌──────────────┐
│ Generate Hash│ ← MD5 of document content
└──────┬───────┘
       │
       ▼
┌──────────────┐    Yes    ┌──────────────┐
│ Hash Changed? │──────────▶│ Index to     │
└──────┬───────┘           │ Neural DB    │
       │ No                 └──────────────┘
       ▼
┌──────────────┐
│ Skip (Up to  │
│ date)         │
└──────────────┘
```

**Sync Functions:**
- `sync_flights()`: Convert FlightOffer objects to documents
- `sync_hotels()`: Convert hotel data to documents
- `sync_events()`: Convert event data to documents

---

## Data Flow

### Search Flow

```
User Query
    │
    ▼
┌─────────────────────────────────────┐
│ 1. Check for live data keywords      │
│    ("live price", "current")        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 2. Execute Neural Search           │
│    - Generate embeddings             │
│    - Query ChromaDB                  │
│    - Apply reranking (optional)      │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│ 3. Evaluate Results                  │
│    - Count >= threshold?             │
│    - Staleness check                 │
│    - Entity match check              │
└─────────────────────────────────────┘
    │
    ├─ Yes ──▶ Return Neural Results
    │
    └─ No ───▶ Failover to Scrapers
                  │
                  ▼
         ┌──────────────────┐
         │ Execute Scrapers │
         │ (Async parallel) │
         └──────────────────┘
                  │
                  ▼
         ┌──────────────────┐
         │ Merge Results    │
         │ (Hybrid mode)    │
         └──────────────────┘
                  │
                  ▼
         Return Combined Results
```

### Indexing Flow

```
Scraper Execution
      │
      ▼
┌──────────────────┐
│ Parse Results     │
│ (JSON/Objects)    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Generate Document │
│ with Metadata     │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    New    ┌──────────────────┐
│ Check Content    │──────────▶│ Chunk Text       │
│ Hash vs Last     │           │ (512 tokens)     │
│ Sync             │           └────────┬─────────┘
└────────┬─────────┘                    │
         │ Changed                      ▼
         │                     ┌──────────────────┐
         │                     │ Generate         │
         │                     │ Embeddings       │
         │                     └────────┬─────────┘
         │                            │
         │                            ▼
         │                   ┌──────────────────┐
         │                   │ Index to         │
         │                   │ ChromaDB         │
         │                   └──────────────────┘
         │
         ▼
┌──────────────────┐
│ Skip (No Change) │
└──────────────────┘
```

---

## Performance Characteristics

### Latency Budgets

| Operation | Expected Latency | Notes |
|-----------|------------------|-------|
| Neural Search | 50-200ms | Depends on result count |
| Cross-encoder Rerank | +50-100ms | Optional, improves relevance |
| Scraper Fallback | 2-10s | Network dependent |
| Total (Neural) | <300ms | Fast path |
| Total (Failover) | 3-12s | Includes scraper time |

### Throughput

- Neural Search: 100+ queries/sec (local)
- Scraper Fallback: 1-5 queries/sec (rate limited)
- Indexing: ~100 docs/minute with embeddings

---

## Error Handling

### Failure Scenarios

1. **Neural Search Unavailable**
   - Detection: Connection error to ChromaDB
   - Action: Immediate failover to scrapers
   - User Impact: Higher latency, live data

2. **Scraper Failure**
   - Detection: Timeout or HTTP error
   - Action: Return neural results only (if available)
   - User Impact: May be stale data

3. **Empty Results**
   - Detection: Both neural and scrapers return nothing
   - Action: Return empty result with helpful message
   - User Impact: Clear feedback

4. **Partial Failover**
   - Detection: Some scrapers fail, others succeed
   - Action: Combine available results
   - User Impact: Partial results with notice

---

## Configuration

### search_config.json

```json
{
  "primary_search": "neural",
  "fallback_enabled": true,
  "neural_threshold": 3,
  "staleness_days": 7,
  "collections": ["web", "events", "travel_data"],
  "auto_index": true,
  "index_schedule": "daily",
  "cache_enabled": true,
  "cache_ttl_seconds": 300,
  
  "neural_search": {
    "db_path": "/home/ubuntu/.openclaw/neural_search_db",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "default_limit": 10,
    "default_threshold": 0.3,
    "rerank_enabled": true
  },
  
  "quality_metrics": {
    "min_result_score": 0.5,
    "max_latency_ms": 5000,
    "track_user_feedback": true
  }
}
```

---

## Benefits

### For Users
- **Faster Search**: Neural search is 10-100x faster than scrapers
- **Better Results**: Semantic understanding finds relevant matches
- **Available Offline**: Neural works without internet (local DB)
- **Transparent**: Clear indication of data freshness

### For System
- **Reduced Load**: Fewer scraper calls = less rate limiting
- **Lower Costs**: No API fees for neural search
- **Better Caching**: Semantic results cacheable
- **Scalability**: Local neural search scales with hardware

---

## Trade-offs

| Aspect | Neural Search | Scraper Fallback |
|--------|---------------|------------------|
| Speed | ✓ Fast | ✗ Slow (2-10s) |
| Freshness | ✗ Stale (up to 7 days) | ✓ Live |
| Cost | ✓ Free (local) | ✗ Rate limits |
| Coverage | ✓ All indexed data | ✗ Current only |
| Semantic Match | ✓ Yes | ✗ Keyword only |

---

## Future Enhancements

1. **A/B Testing Framework**
   - Compare neural vs scraper result quality
   - Track user click-through rates
   - Auto-optimize thresholds

2. **Real-time Index Updates**
   - Webhook-based indexing
   - Stream scraper outputs to neural

3. **Smart Fallback**
   - Learn user preferences
   - Predict when failover needed

4. **Multi-modal Search**
   - Image search for venues
   - Voice query support

---

## Related Documents

- [MIGRATION_GUIDE.md](./MIGRATION_GUIDE.md) - Step-by-step implementation
- [TESTING_STRATEGY.md](./TESTING_STRATEGY.md) - Verification and testing
- Neural Search Docs: `/projects/neural-search/README.md`
- Travel Scout Docs: `/projects/travel-scout/README.md`
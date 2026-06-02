# Migration Guide

Step-by-step instructions for implementing the Neural Search integration into Travel Scout.

---

## Phase 1: Preparation (30 minutes)

### 1.1 Verify Prerequisites

```bash
# Check neural-search is available
cd /home/ubuntu/.openclaw/workspace/projects/neural-search
python3 -c "from src.vector_store import VectorStore; print('✓ Neural search available')"

# Check ChromaDB data exists
ls -la ~/.openclaw/neural_search_db/

# Verify travel-scout structure
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout
ls backend/app/scrapers/
```

### 1.2 Backup Current State

```bash
# Backup existing code
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout
cp -r backend backend.backup.$(date +%Y%m%d)

# Backup neural search data (optional)
cp -r ~/.openclaw/neural_search_db ~/.openclaw/neural_search_db.backup.$(date +%Y%m%d)
```

### 1.3 Install Integration

The integration is already in place at:
```
/projects/travel-scout/neural-integration/
```

Copy to proper location:
```bash
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout

# Copy integration files
cp -r neural-integration/travel_scout backend/app/

# Copy config
cp neural-integration/travel_scout/config/search_config.json backend/app/config/
```

---

## Phase 2: Configuration (15 minutes)

### 2.1 Update Python Path

Add to `backend/app/__init__.py`:
```python
import sys
from pathlib import Path

# Add neural search to path
NEURAL_PATH = Path("/home/ubuntu/.openclaw/workspace/projects/neural-search")
sys.path.insert(0, str(NEURAL_PATH))

# Add integration module
sys.path.insert(0, str(Path(__file__).parent))
```

### 2.2 Update search_config.json

Edit `/projects/travel-scout/backend/app/config/search_config.json`:

```json
{
  "primary_search": "neural",
  "fallback_enabled": true,
  "neural_threshold": 3,
  "staleness_days": 7,
  "collections": ["web", "events", "travel_data"],
  "auto_index": true,
  "index_schedule": "daily",
  "index_time": "02:00",
  "metrics_enabled": true,
  "neural_search": {
    "db_path": "/home/ubuntu/.openclaw/neural_search_db",
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "default_limit": 10,
    "default_threshold": 0.3
  },
  "scraper": {
    "timeout_seconds": 30,
    "max_retries": 3
  }
}
```

### 2.3 Create Logs Directory

```bash
mkdir -p /home/ubuntu/.openclaw/workspace/projects/travel-scout/backend/app/logs
```

---

## Phase 3: Scraper Integration (45 minutes)

### 3.1 Create Scraper Wrappers

Create `backend/app/scrapers/neural_wrappers.py`:

```python
"""
Neural Search wrapper functions for existing scrapers.
Converts scraper output to standardized format.
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import date

from app.scrapers.flight_scraper import search_flights, FlightOffer
from travel_scout.search_router import SearchRouter
from travel_scout.index_sync import sync_flights


async def search_flights_with_neural(
    origin: str,
    destination: str,
    date_from: date,
    date_to: Optional[date] = None,
    max_price: Optional[float] = None,
    use_neural: bool = True
) -> Dict[str, Any]:
    """
    Search flights with neural-first approach.
    
    Args:
        origin: Origin airport code
        destination: Destination airport code
        date_from: Departure date
        date_to: Return date
        max_price: Maximum price filter
        use_neural: Try neural search first
        
    Returns:
        Dictionary with results and metadata
    """
    router = SearchRouter()
    
    if use_neural:
        # Try neural search first
        neural_results = router.unified_search(
            query=f"flights from {origin} to {destination}",
            search_type="flights",
            date_range=(date_from, date_to or date_from),
            filters={"max_price": max_price} if max_price else None
        )
        
        # Check if we got good results
        if neural_results.total_results >= 3:
            return {
                "source": "neural",
                "results": neural_results.results,
                "latency_ms": neural_results.latency_ms,
                "cached": neural_results.cached
            }
    
    # Fallback to scraper
    scraper_results = await search_flights(origin, destination, date_from, date_to, max_price)
    
    # Optionally sync to neural for future
    if use_neural:
        await asyncio.create_task(
            sync_flights_async([r.__dict__ for r in scraper_results])
        )
    
    return {
        "source": "scraper",
        "results": scraper_results,
        "latency_ms": None,  # Calculate from scraper
        "cached": False
    }


async def sync_flights_async(flights: List[Dict]):
    """Async wrapper for flight sync."""
    sync_flights(flights)
```

### 3.2 Modify Existing API Endpoints

Update `backend/app/routers/recommendations.py`:

```python
from travel_scout.search_router import SearchRouter

# Create router instance (at module level for reuse)
search_router = SearchRouter()

@router.get("/search/flights")
async def search_flights_endpoint(
    origin: str,
    destination: str,
    date: str,
    return_date: Optional[str] = None,
    max_price: Optional[float] = None,
    prefer_live: bool = False  # New parameter
):
    """
    Search for flights with neural-first approach.
    Set prefer_live=True to skip neural and go directly to scrapers.
    """
    from datetime import datetime
    
    date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    return_date_obj = datetime.strptime(return_date, "%Y-%m-%d").date() if return_date else None
    
    results = search_router.search_flights(
        origin=origin,
        destination=destination,
        depart_date=date_obj,
        return_date=return_date_obj,
        max_price=max_price
    )
    
    return {
        "success": True,
        "data": results.to_dict()
    }
```

---

## Phase 4: Index Existing Data (30 minutes)

### 4.1 Create Migration Script

Create `scripts/migrate_to_neural.py`:

```python
#!/usr/bin/env python3
"""
Migrate existing Travel Scout data to Neural Search.
"""
import json
import asyncio
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, "/home/ubuntu/.openclaw/workspace/projects/travel-scout/backend")
sys.path.insert(0, "/home/ubuntu/.openclaw/workspace/projects/neural-search")

from travel_scout.index_sync import IndexSync, sync_flights


def load_sample_data():
    """Load existing scraper data or create sample."""
    data_dir = Path("/home/ubuntu/.openclaw/workspace/data")
    
    flights = []
    events = []
    hotels = []
    
    # Load from JSON files if they exist
    for file in data_dir.glob("*.json"):
        try:
            with open(file) as f:
                data = json.load(f)
                if "flight" in file.name.lower():
                    flights.extend(data if isinstance(data, list) else [data])
                elif "event" in file.name.lower():
                    events.extend(data if isinstance(data, list) else [data])
                elif "hotel" in file.name.lower():
                    hotels.extend(data if isinstance(data, list) else [data])
        except Exception as e:
            print(f"Error loading {file}: {e}")
    
    return flights, events, hotels


def create_sample_flights():
    """Create sample flight data for initial index."""
    return [
        {
            "origin": "MPM",
            "destination": "LHR",
            "airline": "British Airways",
            "price": 850,
            "currency": "USD",
            "depart_date": "2026-06-01",
            "duration_minutes": 600,
            "stops": 0,
            "booking_link": "https://example.com/flights/MPM-LHR-BA"
        },
        {
            "origin": "MPM",
            "destination": "JNB",
            "airline": "South African Airways",
            "price": 450,
            "currency": "USD",
            "depart_date": "2026-06-01",
            "duration_minutes": 90,
            "stops": 0,
            "booking_link": "https://example.com/flights/MPM-JNB-SAA"
        }
    ]


def main():
    print("Starting migration to Neural Search...")
    print("=" * 60)
    
    # Initialize sync
    sync = IndexSync(collection="travel_data")
    
    # Load or create data
    flights, events, hotels = load_sample_data()
    
    if not flights:
        print("No existing flight data found. Creating samples...")
        flights = create_sample_flights()
    
    # Index flights
    print(f"\nIndexing {len(flights)} flights...")
    result = sync_flights(flights)
    print(f"Status: {result.status.value}")
    print(f"Indexed: {result.documents_indexed}")
    print(f"Failed: {result.documents_failed}")
    
    # Index events
    if events:
        print(f"\nIndexing {len(events)} events...")
        # Similar process for events
    
    # Index hotels
    if hotels:
        print(f"\nIndexing {len(hotels)} hotels...")
        # Similar process for hotels
    
    print("\n" + "=" * 60)
    print("Migration complete!")
    print(f"Timestamp: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
```

### 4.2 Run Migration

```bash
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout/backend
python3 ../scripts/migrate_to_neural.py
```

---

## Phase 5: Testing (30 minutes)

### 5.1 Run Unit Tests

```bash
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout/neural-integration
python3 -m pytest tests/ -v
```

### 5.2 Integration Tests

```python
# tests/test_integration.py
def test_neural_search():
    from travel_scout.search_router import SearchRouter
    
    router = SearchRouter()
    results = router.unified_search("flights to London")
    
    assert results is not None
    assert results.source in ["neural", "scraper", "hybrid"]
    print(f"✓ Search returned {results.total_results} results from {results.source}")


def test_failover():
    from travel_scout.search_router import SearchRouter
    
    router = SearchRouter()
    # Query that won't match anything
    results = router.unified_search("xyzabc123nonexistent")
    
    # Should failover to scrapers or return empty
    assert results.failover_reason is not None or results.total_results == 0
    print(f"✓ Failover reason: {results.failover_reason}")
```

---

## Phase 6: Production Deployment (30 minutes)

### 6.1 Create Systemd Service (Optional)

Create `/etc/systemd/system/travel-scout-neural.service`:

```ini
[Unit]
Description=Travel Scout Neural Search Integration
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/.openclaw/workspace/projects/travel-scout/backend
Environment=PYTHONPATH=/home/ubuntu/.openclaw/workspace/projects/neural-search
Environment=NEURAL_SEARCH_DB_PATH=/home/ubuntu/.openclaw/neural_search_db
ExecStart=/usr/bin/python3 -c "from travel_scout.search_router import SearchRouter; router = SearchRouter(); print('Neural search ready')"
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl enable travel-scout-neural
sudo systemctl start travel-scout-neural
```

### 6.2 Setup Daily Re-indexing

Add to crontab:
```bash
# Edit crontab
crontab -e

# Add line for daily 2 AM re-index
0 2 * * * cd /home/ubuntu/.openclaw/workspace/projects/travel-scout/backend && python3 -c "from travel_scout.index_sync import IndexSync; IndexSync().sync_from_directory('/home/ubuntu/.openclaw/workspace/data')" >> /home/ubuntu/.openclaw/workspace/projects/travel-scout/backend/logs/index_sync.log 2>&1
```

### 6.3 Update Health Check

Add neural search health check:

```python
# In your health check endpoint
@app.get("/health")
async def health_check():
    status = {"status": "healthy", "components": {}}
    
    # Check neural search
    try:
        from travel_scout.neural_client import create_client
        client = create_client()
        stats = client.get_collection_stats()
        status["components"]["neural_search"] = "healthy"
        status["components"]["neural_collections"] = list(stats.get("collections", {}).keys())
    except Exception as e:
        status["components"]["neural_search"] = f"unhealthy: {str(e)}"
        status["status"] = "degraded"
    
    return status
```

---

## Verification Checklist

- [ ] Neural search initializes without errors
- [ ] Search router responds to queries
- [ ] Failover triggers correctly for insufficient results
- [ ] Scraper fallback works when neural unavailable
- [ ] Index sync completes successfully
- [ ] Metrics are being collected
- [ ] Health check endpoint reports status correctly
- [ ] Logs are being written to `backend/logs/`
- [ ] Daily re-index cron job is scheduled

---

## Rollback Procedure

If issues occur:

```bash
# 1. Stop using neural integration
cd /home/ubuntu/.openclaw/workspace/projects/travel-scout/backend

# 2. Revert to old API endpoints
cp backend.backup.*/app/routers/recommendations.py app/routers/

# 3. Remove neural integration from imports
# Edit files to remove travel_scout imports

# 4. Restart services
sudo systemctl restart travel-scout-neural  # if using systemd

# 5. Verify old scrapers still work
python3 -c "from app.scrapers.flight_scraper import search_flights; print('OK')"
```

---

## Troubleshooting

### Issue: "Neural search modules not available"

**Solution:**
```bash
# Verify neural-search path
export PYTHONPATH="/home/ubuntu/.openclaw/workspace/projects/neural-search:$PYTHONPATH"
python3 -c "from src.vector_store import VectorStore; print('OK')"
```

### Issue: "No collections found"

**Solution:**
```bash
# Check if ChromaDB data exists
ls -la ~/.openclaw/neural_search_db/

# Re-index sample data
cd /home/ubuntu/.openclaw/workspace/projects/neural-search
./neural_index.py directory /home/ubuntu/.openclaw/workspace/projects/neural-search/docs --collection docs
```

### Issue: "Failover too aggressive"

**Solution:** Adjust thresholds in config:
```json
{
  "neural_threshold": 1,  // Lower threshold
  "staleness_days": 14    // Allow older data
}
```

---

## Next Steps

1. **Monitor Metrics**: Check logs for failover rates and latencies
2. **Tune Thresholds**: Adjust based on observed behavior
3. **Expand Coverage**: Index more data sources
4. **A/B Testing**: Compare neural vs scraper user satisfaction
5. **Optimization**: Add caching layers where needed
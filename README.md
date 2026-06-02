# Travel Scout SaaS

A flight and event alert system where users can login, set travel interests, and receive Telegram/WhatsApp/Email notifications when deals match their preferences.

## New: Neural Search Integration ✨

Travel Scout now integrates with the **Neural Search System** for semantic event discovery. This enables natural language queries like:

- "F1 races in Europe this summer"
- "Hip hop concerts in London"
- "Formula 1 British Grand Prix"

The neural search system provides:
- **Semantic understanding**: Finds relevant events even without exact keyword matches
- **Multi-source indexing**: Searches across F1 calendars, concert listings, venue sites
- **Automatic failover**: Falls back to scrapers if neural results are insufficient
- **Zero API costs**: Fully local, no external search API fees

## Tech Stack

- **Backend**: Python FastAPI (async)
- **Database**: PostgreSQL with SQLAlchemy 2.0 + asyncpg
- **Frontend**: Next.js 14 (App Router, TypeScript)
- **Auth**: JWT-based authentication
- **Notifications**: Telegram Bot API, Resend (email), WhatsApp (placeholder)
- **AI/Search**: Neural Search System (local vector search with ChromaDB + Sentence Transformers)

## Quick Start

### 1. Start Database Services

**Option A: Docker Compose (recommended)**
```bash
cd travel-scout
docker-compose up -d
```

**Option B: Manual Docker**
```bash
# PostgreSQL
docker run -d --name travel-scout-postgres \
  -e POSTGRES_USER=travel_scout \
  -e POSTGRES_PASSWORD=travel_scout_dev \
  -e POSTGRES_DB=travel_scout \
  -p 5432:5432 postgres:15-alpine

# Redis
docker run -d --name travel-scout-redis -p 6379:6379 redis:7-alpine
```

**Option C: Local installation**
```bash
# Install PostgreSQL 15+ and Redis 7+ locally
# Create database: createdb travel_scout
# Start redis-server
```

### 2. Backend Setup

```bash
cd backend
cp .env.example .env

# Configure your tokens in .env:
# - TELEGRAM_BOT_TOKEN
# - RESEND_API_KEY
# - JWT_SECRET_KEY

# Using virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Backend runs on `http://localhost:8001`

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:3000`

## Neural Search CLI Commands

The new neural search CLI tools are available at the project root:

### Search Events
```bash
# Search for F1 races
python search_events.py "F1 races" --limit 10

# Search concerts with filters
python search_events.py "hip hop concerts" --location "London" --date-from 2026-06-01 --date-to 2026-08-31

# Search with event type filter
python search_events.py "Formula 1" --type f1 --json

# Save results to file
python search_events.py "music festivals" --save festivals.json
```

### Build Itinerary
```bash
# Build complete trip itinerary
python build_itinerary.py --event "F1 British GP" --dates "2026-07-18:2026-07-20" --origin "Maputo"

# With interests and budget
python build_itinerary.py --event "concerts" --dates "2026-06-01:2026-06-05" --interests "rock,indie" --budget mid

# Save to file
python build_itinerary.py --event "Silverstone" --dates "2026-07-18" --save silverstone_trip.json
```

### Python API Usage

```python
from event_search import EventSearcher, search_events
from itinerary_builder import ItineraryBuilder

# Event search
results = search_events(
    query="F1 races",
    location="Europe",
    date_from="2026-06-01",
    date_to="2026-08-31",
    event_type="f1",
    limit=10
)

# Specialized searches
searcher = EventSearcher()
concerts = searcher.search_concerts(location="London", genre="hip hop")
f1_races = searcher.search_f1_races(location="Europe")
sports = searcher.search_sports(location="Madrid", sport_type="football")

# Build itinerary
itinerary = create_itinerary(
    event_query="F1 British GP",
    dates="2026-07-18:2026-07-20",
    origin="Maputo",
    interests=["F1", "motorsport"],
    budget_level="mid"
)
```

## Features

### Current (MVP)
- User registration and JWT authentication
- Create and manage travel interests (origin, destination, budget)
- Flight alert matching system with multi-source search:
  - Kiwi.com API (primary)
  - Aviasales (secondary)
  - Google Flights (fallback)
  - Sample data (always-available fallback)
- Telegram and email notification delivery
- Dashboard with interests and alerts management

### Neural Search Features (New)
- **Semantic event search**: Natural language queries for events
- **Event type filtering**: concerts, F1, sports, festivals
- **Date range filtering**: Find events within specific dates
- **Location-based search**: Filter by city, region, or country
- **Itinerary builder**: Combines events + flights + hotels
- **Cost estimation**: Breaks down total trip costs

### Planned (AI-Powered)
- Natural language interest input ("I want to go to Europe under $500")
- Smart deal scoring using MiroFish swarm intelligence
- Predictive price analysis (best time to book)
- Personalized itinerary generation

## API Endpoints

### Core Endpoints
| Endpoint | Description |
|----------|-------------|
| `POST /api/auth/register` | Create account |
| `POST /api/auth/login` | Login, returns JWT |
| `GET /api/auth/me` | Get current user |
| `GET /api/interests` | List user's interests |
| `POST /api/interests` | Create interest |
| `PUT /api/interests/{id}` | Update interest |
| `DELETE /api/interests/{id}` | Remove interest |
| `GET /api/alerts` | List matched alerts |
| `POST /api/notifications/test` | Send test notification |

### Neural Search Endpoints (New)
| Endpoint | Description |
|----------|-------------|
| `GET /api/neural/health` | Neural search system status |
| `POST /api/neural/events/search` | Search events with neural search |
| `GET /api/neural/events/concerts` | Search concerts by location/genre |
| `GET /api/neural/events/f1` | Search F1 races |
| `GET /api/neural/events/sports` | Search sports events |
| `GET /api/neural/events/festivals` | Search festivals |
| `POST /api/neural/itinerary/build` | Build complete itinerary |
| `POST /api/neural/unified/search` | Unified search (neural + scrapers) |

### AI Endpoints (Placeholder)
| Endpoint | Description |
|----------|-------------|
| `POST /api/ai/parse-interest` | Parse natural language |
| `POST /api/ai/score-deals` | AI score deals |
| `GET /api/ai/predict-window/{destination}` | Predict booking window |

## Neural Search Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Travel Scout Bot                         │
├─────────────────────────────────────────────────────────────┤
│  CLI Tools:         Backend API:         Frontend:          │
│  - search_events.py  - neural_search.py   - Dashboard      │
│  - build_itinerary  - /api/neural/*      - Event Search    │
│                                                           │
│  Python API:        - /events/search      - Itinerary Builder│
│  - EventSearcher    - /itinerary/build                    │
│  - ItineraryBuilder                                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Neural Integration                       │
├─────────────────────────────────────────────────────────────┤
│  Search Router → Search Orchestrator → Neural Client       │
│       │                                                │
│       ▼                                                │
│  ┌─────────┐    ┌─────────────┐    ┌──────────────┐   │
│  │Scrapers │◄───│  Fallback   │    │Vector Search │   │
│  │(Flights│    │  Logic      │───►│  (ChromaDB)  │   │
│  │ Hotels)│    │             │    └──────────────┘   │
│  └─────────┘    └─────────────┘          │            │
│                                           ▼            │
│                              ┌────────────────────────┐  │
│                              │  Embedding Engine      │  │
│                              │  (sentence-transformers)│  │
│                              └────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Neural Search Configuration

The neural search system is configured in `neural-integration/travel_scout/config/search_config.json`:

```json
{
  "primary_search": "neural",
  "fallback_enabled": true,
  "neural_threshold": 3,
  "staleness_days": 7,
  "collections": ["web", "events", "travel_data"]
}
```

- **neural_threshold**: Minimum results before fallback to scrapers
- **staleness_days**: Maximum age of neural results before refresh
- **fallback_enabled**: Allow scraper fallback when neural results insufficient

## Project Structure

```
travel-scout/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry (now with neural router)
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── interests.py
│   │   │   ├── alerts.py
│   │   │   ├── notifications.py
│   │   │   ├── recommendations.py
│   │   │   └── neural_search.py  # NEW: Neural search endpoints
│   │   ├── services/
│   │   ├── scrapers/
│   │   └── notifications/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── app/
├── neural-integration/         # NEW: Neural search integration
│   └── travel_scout/
│       ├── search_router.py      # Main search interface
│       ├── search_orchestrator.py # Routing logic
│       ├── neural_client.py      # Neural search client
│       └── index_sync.py         # Data sync to neural index
├── search_events.py             # NEW: Event search CLI
├── build_itinerary.py           # NEW: Itinerary builder CLI
├── event_search.py              # NEW: Event search module
├── itinerary_builder.py         # NEW: Itinerary module
├── docker-compose.yml
└── README.md
```

## Neural Search Data Sources

The neural search system indexes content from:
- **F1 Calendar**: Official Formula 1 race schedules
- **Concert Listings**: Music event listings
- **Venue Information**: Event venue details
- **Travel Sites**: Flight and hotel information

To add new sources:
```bash
cd /home/ubuntu/.openclaw/workspace/projects/neural-search
./neural_index.py url <url> --collection web
./neural_index.py rss <feed_url> --collection news
```

## License

MIT
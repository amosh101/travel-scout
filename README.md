# Travel Scout SaaS

A flight and event alert system where users can login, set travel interests, and receive Telegram/WhatsApp/Email notifications when deals match their preferences.

## Tech Stack

- **Backend**: Python FastAPI (async)
- **Database**: PostgreSQL with SQLAlchemy 2.0 + asyncpg
- **Frontend**: Next.js 14 (App Router, TypeScript)
- **Auth**: JWT-based authentication
- **Notifications**: Telegram Bot API, Resend (email), WhatsApp (placeholder)
- **AI Integration**: MiroFish Swarm Intelligence (placeholder for future)

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

### Planned (AI-Powered)
- Natural language interest input ("I want to go to Europe under $500")
- Smart deal scoring using MiroFish swarm intelligence
- Predictive price analysis (best time to book)
- Personalized itinerary generation

## API Endpoints

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
| `POST /api/ai/parse-interest` | Parse natural language (placeholder) |
| `POST /api/ai/score-deals` | AI score deals (placeholder) |
| `GET /api/ai/predict-window/{destination}` | Predict booking window (placeholder) |

## MiroFish AI Integration

This project includes a placeholder for MiroFish Swarm Intelligence integration:

- **Location**: `backend/app/services/ai_recommendations.py`
- **Current**: Simple rule-based matching
- **Future**: Connect to MiroFish (localhost:5001) for:
  - Natural language interest parsing
  - Multi-factor deal scoring (airline reliability, weather, events)
  - Predictive price analysis
  - Personalized itinerary generation

To enable MiroFish integration in the future:
1. Start MiroFish via Docker: `docker-compose -f MiroFish/docker-compose.yml up -d`
2. Update `ai_recommendations.py` to set `self.enabled = True`
3. Update endpoints to call MiroFish APIs

## Project Structure

```
travel-scout/
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI entry
│   │   ├── config.py         # Settings
│   │   ├── database.py       # SQLAlchemy setup
│   │   ├── models/           # SQLAlchemy models
│   │   ├── routers/          # API endpoints
│   │   ├── services/         # Business logic
│   │   ├── scrapers/         # Flight/Event collectors
│   │   └── notifications/    # Telegram/Email dispatch
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/                  # Next.js App Router
│   ├── components/
│   ├── lib/
│   └── package.json
└── docker-compose.yml        # PostgreSQL + Redis
```

## License

MIT
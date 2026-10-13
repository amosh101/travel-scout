# Travel Scout

Travel Scout is a flight and event-travel alert app that lets users create travel interests, browse matching opportunities, and receive updates for relevant trips and events.

## Current status

This branch is a working MVP with an additional neural event-discovery layer, but it is not a full production deployment.

### Verified status
- Backend code compiles successfully
- Frontend production build passes with the standard Next.js build command
- The repo includes a neural-search feature set in addition to the core app flows

### What is working
- User registration and login with JWT auth
- Protected user profile and dashboard flows
- Interest creation, update, and deletion
- Alert and recommendation API routes
- Notification hooks for Telegram and email delivery
- Neural event search and itinerary-builder scripts/endpoints when the supporting neural-integration assets are present

### What is still incomplete or optional
- Live production credentials are not fully configured by default
- Docker/Postgres/Redis infrastructure must be started locally or in deployment environment
- Real-time scheduled matching jobs are not a full production scheduler yet
- Automated AI scoring is still lightweight and not backed by a live external service
- There is no active MiroFish integration in the current codebase; the old MiroFish references are placeholder-only and not connected to the live app flow

---

## Tech stack

- Backend: Python, FastAPI
- API validation: Pydantic
- Database: PostgreSQL, SQLAlchemy 2.0, asyncpg
- Cache/local infra: Redis, Docker Compose
- Frontend: Next.js 14, React, TypeScript
- Styling: Tailwind CSS
- Auth: JWT + bcrypt
- Notifications: Telegram Bot API, Resend email API
- Event discovery: local neural-search tooling with `neural-integration/`, `search_events.py`, and itinerary builder scripts
- AI layer: no active MiroFish integration in this branch; placeholder references remain in legacy service files only

---

## Feature set

### Core app features
- Registration and login
- Travel interest CRUD
- Alert/recommendation endpoints
- Telegram and email notification testing
- Dashboard and protected frontend pages

### Neural search features
- Semantic event discovery for queries like F1, concerts, festivals, and sports
- Date- and location-based filtering
- Event-type matching across multiple event categories
- Local itinerary-building workflow for trip planning

### Planned / future work
- Production hardening and environment configuration
- Scheduled monitoring jobs for repeated deal checks
- Better provider integrations and richer scoring logic
- External AI integration if needed, but not currently activated in this repo

---

## Quick start

### 1) Start infrastructure

```bash
docker compose up -d
```

This brings up PostgreSQL and Redis via the project Docker config.

### 2) Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Required environment values include:
- JWT_SECRET_KEY
- TELEGRAM_BOT_TOKEN
- RESEND_API_KEY

The API runs at http://localhost:8001

### 3) Frontend setup

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at http://localhost:3000

---

## API overview

### Core routes
- `/api/auth` — registration, login, profile lookup
- `/api/interests` — travel-interest CRUD
- `/api/alerts` — alert listing and matching
- `/api/notifications` — test and rich notification delivery
- `/api/ai` — recommendation and booking-window helper endpoints

### Neural routes
- `/api/neural/health` — neural-search availability check
- `/api/neural/events/search` — event search
- `/api/neural/events/concerts` — concert search
- `/api/neural/events/f1` — F1 search
- `/api/neural/events/sports` — sports search
- `/api/neural/events/festivals` — festival search
- `/api/neural/itinerary/build` — itinerary building

FastAPI docs are available at http://localhost:8001/docs when the backend is running.

---

## Project structure

```text
travel-scout/
├── backend/
│   ├── app/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── middleware/
│   │   ├── models/
│   │   ├── notifications/
│   │   ├── routers/
│   │   ├── scrapers/
│   │   └── services/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
├── neural-integration/
├── scripts/
├── search_events.py
├── build_itinerary.py
├── event_search.py
├── itinerary_builder.py
├── docker-compose.yml
├── README.md
├── IMPLEMENTATION_SUMMARY.md
├── PRODUCTION_READINESS_REPORT.md
├── NOTIFICATION_UPDATE_SUMMARY.md
├── NEURAL_INTEGRATION_SUMMARY.md
└── shared_data_integration.py
```

---

## MiroFish note

There is no active MiroFish service integration in the current branch.

The project contains legacy placeholder references in the AI recommendation service and a helper module, but those are not connected to the main app as a running feature. This README intentionally does not present MiroFish as an active capability of the project.

---

## License

MIT
# Travel Scout v2

SaaS that intersects a user's travel interests with real events + flight prices
to surface unique itineraries the user wouldn't find by searching flights or
events alone.

## v1 → v2

v1 shipped a Telegram-first MVP. v2 pivots to a **SaaS-shaped product** with a
Next.js/React web UI for the **user journey** (auth → interests → find trips →
save trips) and an **admin journey** (users, sources, weights, reports).

What's preserved from v1: the interest schema (origin, destination, keywords,
budget, flexibility), the JWT auth pattern, the SQLAlchemy 2 async stack.

What's redesigned: roles (boolean → role+permission tables), billing (none →
Stripe tiers + tier guard), audit (none → audit log + request id), third-party
clients (hardcoded → DB-driven factory, no-fake-data), UI (Telegram → web).

## Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, Postgres 16,
  Redis, Stripe
- **Frontend:** Next.js 14 (App Router), TypeScript strict, Tailwind +
  shadcn/ui, TanStack Query, Zustand
- **Infra:** docker-compose (api, web, postgres, redis, scheduler)

## Quick start

```bash
# 1. Copy env
cp .env.example .env
# Edit .env: JWT_SECRET_KEY, STRIPE_*, *_API_KEY

# 2. Boot
docker compose up -d

# 3. Migrate + seed
docker compose exec api alembic upgrade head
docker compose exec api python -m scripts.seed_reference

# 4. Open
# Web:  http://localhost:3000
# API:  http://localhost:8000/docs
```

## Layout

```
travel-scout/
├── backend/        FastAPI app (routers, models, services, clients, tests)
├── frontend/       Next.js 14 app router
├── infra/          docker-compose, scripts
├── scripts/        Reference data seeders
└── docs/           Architecture, ops, data-source decisions
```

## Personas & permissions

| Role         | Scope                                               |
|--------------|------------------------------------------------------|
| `superadmin` | All permissions; auto-granted to first registered user |
| `admin`      | Users, sources, weights, reports                    |
| `curator`    | Reference data (interests, destinations, events)    |
| `support`    | Read user data, no edits                            |
| `finance`    | Subscriptions, bookings, Stripe                     |
| `agent`      | Booking queue, user messaging                       |
| (end user)   | Self-only                                           |

Permissions are strings (e.g. `user.create`, `user.block`, `itinerary.edit`,
`agent.assign`) and live in the `permissions` table — not booleans.

## Tiers

| Tier       | Saves/mo | Searches/mo | Agent |
|------------|----------|-------------|-------|
| `free`     | 3        | 10          | no    |
| `limited`  | 25       | 100         | no    |
| `unlimited`| unlimited| unlimited   | no    |
| `concierge`| unlimited| unlimited   | yes   |

Server-side enforcement via `check_tier_limit`. Client hints are UX only.

## Hard rules (carried from v1)

- No hardcoded credentials anywhere — env-driven via pydantic-settings.
- No mock/seed data in production paths. Reference data is loaded via
  `scripts/seed_reference` and explicitly named.
- All schema changes go through Alembic migrations — no `init_db()` on startup.
- Tests run on SQLite (with portable types), prod on Postgres. Same Python code.
- Tailscale-only admin routes — `ADMIN_ALLOWED_CIDRS` enforced in middleware.

## What's next

This card ships the foundation only. The next three cards build:

1. **User journey** — search, save, profile, billing UI.
2. **Admin journey** — users, sources, weights, reports.
3. **Agent journey** — booking queue, messaging.

See `/tmp/kanban_t3_user_journey.md` for the user-journey spec.
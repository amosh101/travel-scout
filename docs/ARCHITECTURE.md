# Travel Scout v2 — architecture

v2 is a **SaaS-shaped** product with a Next.js/React web UI for the user and
admin journeys. v1 was Telegram-first; v2 deliberately drops that.

## Monorepo layout

```
travel-scout/
├── backend/            FastAPI (async), SQLAlchemy 2, Alembic, Stripe
│   ├── app/
│   │   ├── clients/    Third-party data sources (Kiwi, Ticketmaster, Jolpica)
│   │   ├── middleware/ Request-Id + Tailscale admin gate
│   │   ├── models/     ORM (portable UUID + JSON columns)
│   │   ├── routers/    FastAPI routers (auth, billing, admin_audit, ...)
│   │   ├── services/   authz, tier_guard, audit, seed
│   │   └── main.py     entry point
│   ├── migrations/     Alembic versions
│   ├── tests/          15/15 passing on SQLite
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/           Next.js 14 (app router), TypeScript strict, Tailwind
│   ├── app/            routes (auth/, admin/, agent/, page.tsx, layout.tsx)
│   ├── components/     providers.tsx (TanStack Query)
│   ├── lib/            api.ts, auth-store.ts, server-fetch.ts, utils.ts
│   ├── tailwind.config.ts
│   ├── app/globals.css (black-responsive theme tokens)
│   ├── package.json
│   └── Dockerfile
├── infra/              (placeholder for terraform / ansible, future)
├── scripts/            seed_reference.py
├── docs/               this file
├── docker-compose.yml  postgres + redis + api + web
├── .env.example        every variable, no secrets
└── README.md
```

## Personas & permissions

Permissions are stored in the DB as `permissions.key` strings (e.g.
`user.create`, `user.block`, `audit.read`, `billing.write`) and granted to
roles via a `role_permissions` join table. Users hold roles via `user_roles`
with `granted_by`, `granted_at`, `revoked_at` for full audit history.

| Role        | Notable permissions                                       |
|-------------|-----------------------------------------------------------|
| superadmin  | every permission; auto-granted to the first registered user |
| admin       | user.*, interest.admin, source.admin, weights.update, audit.read |
| curator     | interest.admin, destination.admin, user.read              |
| support     | read-only                                                 |
| finance     | billing.read, billing.write, user.read                    |
| agent       | user.read, agent.work                                     |
| (end user)  | self-only (no role assigned by default)                   |

Adding a permission = `INSERT INTO permissions (key, description)`. Adding a
role = `INSERT INTO roles (key, name, description)`. Linking them =
`INSERT INTO role_permissions`. No code changes required.

## Tier guard

`free / limited / unlimited / concierge` — limits live in the `tier_limits`
table and are read at request time. `usage_counters` row per user per
`period_yyyymm` tracks usage. `check_tier_limit` returns a `TierCheck`
dataclass; `require_tier_allows` raises `TierLimitExceeded` (HTTP 402 with
structured `{tier, action, current, limit, next_step}`).

Client-side hints are UX only — the server is the source of truth.

## Stripe webhook

`POST /api/billing/webhook` verifies the `stripe-signature` header, looks up
the event id in `stripe_events` for idempotency, dispatches by event type,
updates the matching `subscriptions` row and flips `users.tier` on
active/trialing transitions. Audited via `AuditService.record` with
`actor_kind=system`.

The price-id → tier map is wired through `STRIPE_PRICE_*` env vars (lands in
the user-journey card when the Stripe products exist).

## Audit log

Every privileged mutation calls `AuditService.record(...)`. The
`RequestIdMiddleware` attaches a UUID to each request and stores it in a
contextvar; audit entries automatically pick it up. Admin can query via
`GET /api/admin/audit?actor_user_id=&action=&since=&until=&limit=&offset=`.

Admin routes also pass through `TailscaleAdminGate` middleware: requests from
non-allowlisted CIDRs (per `ADMIN_ALLOWED_CIDRS`) get a 403.

## Portable schema

`PortableUUID` (CHAR(36) on SQLite, native UUID on Postgres) and `JSON` (JSON
on SQLite, JSONB on Postgres on Postgres if dialect-aware) let the same
SQLAlchemy code run in tests (SQLite) and prod (Postgres). Lesson carried from
v1, which used Postgres-only `ARRAY(String)` and forced `init_db()` on
startup.

## Out of scope (next cards)

- t3 — user journey (search, save, profile, billing UI)
- t4 — admin journey (users, sources, weights, reports)
- t5 — agent journey (booking queue, messaging)
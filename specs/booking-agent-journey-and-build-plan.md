# Booking Agent Journey — Outline & Build Plan

**Date:** 2026-07-24
**Audience:** Sir + anyone working the travel-scout codebase
**Scope:** What the booking-agent feature is, where it stands today, what
still needs building, and the order to build it.

---

## 1. What the booking agent is

A **human booking agent** (you, or a small team of you) who receives
hand-offs from users, contacts them off-platform to gather passport/date
details, books on their behalf, and reports outcomes back into the app.

The product shape is **human-mediated, not automated**. Users do not get
instant bookings; they get a real person who confirms the trip exists, that
the dates work, that the passport is valid, and that the money moves.

This is the right shape for a China→MZ B2B tourist pipeline because:

- **Payment rails don't span the trip.** Alipay and WeChat Pay don't work in
  Mozambique for hotels; the agent pays with a MZ card and invoices the
  user. Same for visa-prep, SIM, transfer, etc.
- **PII handling needs a person.** Passport numbers, dates of birth,
  emergency contacts — these are best gathered over WhatsApp/email by a
  named agent, not a form on a webpage.
- **Local supply is opaque.** Mozambican hotel inventory and Chinese
  outbound-tour packages are not on Skyscanner. The agent has the contacts.

---

## 2. The user journey (what the user experiences)

There are **two distinct tiers** in the user journey:

### 2A. Free tier — no agent (current default)

```
Discover  ─→  Save  ─→  Outbound booking link  ─→  (user books themselves)
   │              │              │
   │              │              └─ Deep-link to Ctrip / Booking.com / hotel direct
   │              └─ Adds itinerary to /saved
   └─ Anonymous or registered; no human contact
```

User saves the itinerary, the app gives them outbound links, they book
themselves. No BookingsLog row is ever created. No agent involvement.

This works today (T8 shipped this path; deep links via Ctrip/Booking.com).

### 2B. Concierge tier — agent involved (the booking-agent journey)

```
Discover  ─→  Save  ─→  "Hand off to a booking agent"  ─→  Queue  ─→  Claim  ─→  Contact  ─→  Book  ─→  Confirm  ─→  Notify
   │              │                │                          │          │           │          │         │           │
   │              │                │                          │          │           │          │         │           └─ User gets
   │              │                │                          │          │           │          │         │              a Telegram
   │              │                │                          │          │           │          │         │              /message
   │              │                │                          │          │           │          │         └─ Agent posts
   │              │                │                          │          │           │          │            outcome to BookingsLog
   │              │                │                          │          │           │          └─ Agent confirms with
   │              │                │                          │          │           │             hotel/supplier
   │              │                │                          │          │           └─ Agent calls / WhatsApps user,
   │              │                │                          │          │              collects passport + dates
   │              │                │                          │          └─ Agent marks BookingsLog row = claimed
   │              │                │                          └─ BookingsLog row created, status = pending
   │              │                └─ Click on /saved page; "Message my agent" CTA
   │              └─ itinerary saved
   └─ User searches by interests / dates / location
```

The state machine is:

```
                ┌─────────────┐
                │   PENDING   │  ◀── created by user hand-off
                └──────┬──────┘
                       │ agent claims
                       ▼
                ┌─────────────┐
                │   CLAIMED   │
                └──────┬──────┘
                       │ agent starts work (optional)
                       ▼
                ┌─────────────┐
                │ IN_PROGRESS │
                └──────┬──────┘
                       │
            ┌──────────┴──────────┐
            ▼                     ▼
     ┌─────────────┐       ┌─────────────┐
     │  CONFIRMED  │       │   FAILED    │
     │ (paid+booked)│       │ (couldn't   │
     └─────────────┘       │  book)      │
                           └─────────────┘
```

Plus a terminal **`released`** path: agent claims, then un-claims (drops
back to PENDING) if they can't continue. Used when a user is unreachable
or the agent has to escalate.

### 2C. Side journey — the message thread

After the hand-off, the user and the agent communicate via a chat thread
tied to the itinerary. The thread is a 1:1 conversation that lives in
the app (so we have a record + can re-read it later), and is what the
agent uses to:

- Confirm passport/date details the user submitted
- Share photos of hotel confirmations
- Coordinate timezone-sensitive updates (flight delays, hotel swaps)

The thread is **concierge-only** (free-tier users don't get it). The
agent sees it via the admin panel; the user sees it via `/agent-chat`.

### 2D. Side journey — notifications

User and agent both need to know when something changes:

| Event | User gets | Agent gets |
|---|---|---|
| Hand-off created | "We're on it" (immediate) | Telegram + dashboard badge |
| Agent claims | — | "You've been assigned" |
| Agent posts message | "New message from agent" | — |
| Agent confirms booking | "Booking confirmed: details inside" | — |
| Agent fails booking | "Couldn't book — reason inside" | — |

Notifications in v1 go through Telegram (Alfred bot) + the in-app
`/messages` thread; email is a v2 concern (one-time setup cost).

---

## 3. What's already built (live, today)

This is what the live `travel-api` at `100.91.143.50:8000` can do
right now — verified from `git log`, the `agent.py` source, and the
T3/T4 spec files:

### Backend (live on `d6a28e5` + worktree `wt/t3-user` which is unmerged)

- **`POST /api/agent/queue`** — user hand-off, creates `BookingsLog`
  row in PENDING, idempotent, audit-logged. `agent.py:165-248`.
- **`GET /api/agent/queue`** — agent-facing list (gated by
  `agent.work` permission), returns PENDING + items claimed by the
  calling agent. `agent.py:256-295`.
- **`POST /api/agent/queue/{id}/claim`** — race-safe claim; only
  one agent wins, returns 409 if already claimed. `agent.py:298-337`.
- **`POST /api/agent/queue/{id}/release`** — un-claim, with optional
  note appended to metadata. `agent.py:340-380`.
- **`POST /api/agent/queue/{id}/outcome`** — confirm or fail with
  amount/currency/external-id/note. `agent.py:383-431`.
- **`BookingsLog` model** — full state machine columns (status,
  amount_cents, currency, external_id, metadata_json, assigned_agent_id,
  claimed_at, outcome_at, outcome_note). Live in DB.
- **`write_audit_log` integration** — every state transition writes
  an audit entry with `actor_kind=AGENT` for agent actions,
  `actor_kind=USER` for user actions.

### Frontend (NOT live — on `wt/t3-user` worktree, unmerged)

- T3-user delivered 5 pages: `/me`, `/onboarding`, `/saved` updates,
  `/profile`, `/agent-chat` *spec only* — no implementation
- The `/agent-chat` page is **specified** (`specs/card_agent_chat_page.md`)
  but **not built**.
- The `/saved` page has a *spec* for a "Message my agent" CTA but the
  CTA component is not implemented.

### What's *not* built yet

- **`/api/messages` POST + GET** (the chat-thread endpoints). Spec
  lives at `specs/card_post_messages.md` and `card_get_messages.md`
  but the routes don't exist on `d6a28e5`.
- **`/agent-chat` page** (frontend). Spec exists, no Next.js code.
- **"Hand off to agent" button** on `/saved`. Spec at
  `specs/card_saved_cta.md`, not built.
- **Agent-side dashboard** — list/claim/release/outcome from the
  browser. The API exists; only Telegram-style notification or a CLI
  can drive it today.
- **Telegram notifications** to agent when a user hands off, and to
  user when the agent confirms/fails.
- **The migration for the new T3 columns** is in `wt/t3-user`
  (`0002_user_onboarding_fields.py`) but not yet merged to main or
  deployed.

---

## 4. What's NOT in scope for the booking-agent v1

To keep the build honest, here's what v1 deliberately leaves out:

- **Real-time websockets.** Polling every 3s is fine for v1. The cost of
  running a ws server on this VPS (3.8 GB RAM, 0 swap) is not justified
  by message volume.
- **File attachments in chat.** Passport photos come via WhatsApp for v1;
  we link from the message thread to a Drive/OneDrive share. Building
  upload + virus scan + storage is a separate workstream.
- **Multi-agent routing.** v1 has you as the only agent. The schema
  supports multiple agents (`assigned_agent_id` is a FK to `users`),
  but there's no "find least-loaded agent" logic in production yet.
- **Auto-booking integrations.** No Skyscanner API, no Ctrip Partner
  API, no Stripe Connect. v1 is human-mediated end-to-end. Stripe
  invoicing for the agent→user payment is v1.5.
- **Push notifications, email notifications, read receipts.** v1
  notifications are: (a) in-app on `/agent-chat` page, (b) Telegram
  via the Alfred bot cron, (c) email on confirm/fail.
- **Refund/cancellation flow.** `refunded` is a valid status in the
  schema; no endpoints touch it. v1.5 work.
- **Multi-currency handling.** The schema supports per-row currency
  (3-char ISO), but FX conversion and settlement are out of scope.

---

## 5. The build plan

Three phases, sequential. Each phase is independently shippable and
testable.

### Phase A — finish the queue + chat API (3-5 days work)

Goal: the agent-side workflow works end-to-end through the API, even
without a frontend.

Tasks:
1. **`POST /api/messages`** — body `{itinerary_id, body}`; appends to
   the itinerary's thread. Tier guard: `tier == 'concierge'`. Auto-assigns
   to the user's assigned agent (look up from `agent_assignments`; if
   none, least-loaded active agent).
2. **`GET /api/messages?itinerary_id=...&since=...`** — chronological
   list with `since` for polling. Owner-or-concierge-or-agent can read.
3. **`app/schemas/messages.py`** — Pydantic schemas for both endpoints.
4. **Alembic migration** — the T3-user migration
   (`0002_user_onboarding_fields.py`) needs to be renamed to
   `0006_*` and chained to `0005_scraped` before deployment (this is
   the **only** blocker on shipping the existing T3-user code).
5. **Tests** — `test_messages.py`: 201 on POST as concierge, 403 on
   POST as free, GET chronological + `since` filter, audit log on
   POST. Aim for 8-10 tests covering happy path + each auth edge case.
6. **`MessageThread` model** if not already present (verify), plus
   indexes on `(itinerary_id, created_at)` for polling efficiency.

Done when:
- `pytest backend/tests/test_messages.py` passes
- Smoke test from `curl` confirms both endpoints work on the live API
- The T3-user code branch is **deployable to main** (alembic chain
  is fixed, no dirty `__pycache__`, container rebuild succeeds)

### Phase B — frontend surfaces (5-7 days work)

Goal: the user can see and use the agent-chat from their browser, and
the agent can drive the queue from a minimal admin UI.

Tasks (in dependency order):

1. **`/profile` page** — full edit (name, nationality, passport, dob,
   emergency contact, home_airport), change-password, export-data,
   delete-account. Tier badge + "Manage billing" link. This is the
   "T3-user profile" page that lives on `wt/t3-user`.
2. **`/saved` updates** — add the "Message my agent" button (visible
   only for concierge tier + booking_state in `(requested, saved)`)
   and the "Open booking link" CTA (free+ tiers, when
   `outbound_url` exists on the itinerary).
3. **`/agent-chat` page** — two-column: left sidebar of itineraries,
   right pane with the thread view. Poll every 3s. Post box at bottom.
   Redirect to `/itineraries` if `tier != 'concierge'`.
4. **`/admin/agents` page** — minimal agent dashboard: queue list,
   one-click claim, message composer, outcome form. The API is
   already there; this is the UI on top of it. Lives on
   `wt/t4-admin` worktree (uncommitted, unmerged).

Done when:
- All 4 pages render without console errors
- Concierge user can hand-off, see agent message, post reply
- Agent (you, with admin perm) can claim, message, confirm/fail from
  the browser
- `wt/t3-user` is merged into `main`, alembic chain is fixed, image
  is rebuilt, live `travel-api` serves the new pages

### Phase C — notifications + polish (3-5 days work)

Goal: Sir and the user both know when something changes without
opening the app.

Tasks:

1. **Telegram notifications to agent** — when a user hands off, post
   to a dedicated Telegram chat (your personal chat works). Use the
   `tg_send.py` helper that just got built. Cron poll the
   `bookings_log` table for `status='pending'` rows created in the
   last 5 min, notify once per row (de-dup on `row.id`).
2. **Telegram notifications to user** — when the agent posts a
   message, posts an outcome, or claims/releases. Use the same
   `tg_send.py` helper.
3. **In-app unread badge** — count of unread messages on the
   `/agent-chat` sidebar and the global nav. Backed by a `last_read_at`
   column on the `bookings_log` row (or a `message_reads` table; pick
   whichever the team prefers).
4. **Email fallback for v1.5** — when the Telegram delivery fails (no
   chat_id for this user), fall back to email. Use SendGrid free tier
   or AWS SES. Wait until we have a real user with no Telegram to
   justify this.

Done when:
- Hand-off creates a Telegram notification within 60 seconds
- Agent's `/api/messages` post creates a user Telegram notification
  within 60 seconds
- Outcome (confirmed/failed) sends a summary notification
- All notifications are idempotent (re-running the cron doesn't
  duplicate)

---

## 6. Open questions worth one round of clarification

These are the questions whose answers **change the build**, not
"do you want option A or B":

1. **Concierge tier — how do users get it?** Free trial? Paid Stripe
   plan? Invite-only? Today, the schema has `tier` on the user model
   but no `subscriptions` table and no Stripe. Until I know, I'll
   hardcode one user (you) as concierge for the test.
2. **Multi-agent — are you the only agent for v1?** Schema supports
   multiple; v1 logic could be "you + maybe 1-2 friends". Auto-routing
   logic is small either way; the bigger question is onboarding.
3. **Off-platform comms — WhatsApp, WeChat, or just email?** For
   passport/date collection, the agent contacts the user
   off-platform. WhatsApp is the obvious MZ default; WeChat for
   Chinese users. Email is universal but slower. v1 should pick one
   to wire into the Telegram notifications, the others as follow-up.
4. **Payment — agent pays and invoices, or user pays through the app?**
   The `bookings_log` schema has `amount_cents` + `currency` per row,
   which works either way. If user-pays-through-app: Stripe Connect +
   a hold+capture flow is a v1.5 project. If agent-pays-and-invoices:
   simpler — record the amount, send an invoice link.

The answer to all 4 is "Sir, you decide" — but the **decisions**
(not the questions) drive what gets built first.

---

## 7. What's NOT in this outline

- **The Tier-1 SAAS pricing/positioning.** The agent is a feature of the
  travel-scout product, not a standalone product. Pricing fits under
  the larger travel-scout monetisation conversation.
- **Internationalisation of the agent chat.** v1 is English-only; the
  agent and the user both speak English (or use translation off-app).
  Adding bilingual chat (Mandarin↔Portuguese) is a v2 feature.
- **Trip insurance, visa-prep, SIM-card bundles.** All adjacent
  services that an agent could upsell. Schema-wise they fit as
  additional line-items on the itinerary or additional endpoints;
  no schema changes needed.

---

## 8. Status snapshot — what gets verified before "done"

For each phase, the verification gate:

| Phase | Verification |
|---|---|
| A | pytest passes + curl smoke + alembic chain converges + container restart succeeds |
| B | 4 pages render in browser + concierge + free user both work + `wt/t3-user` merged + live API serves new routes |
| C | Telegram notifications arrive within 60s + idempotent under cron reruns + outcome flow delivers a summary |

If any verification fails, the phase is not done, regardless of what
code was written. The pattern is **test first, ship second**, not
**ship first, hope it's right**.

---

## 9. Where this lives

- **This document:** `/root/.hermes/workspace/projects/travel-scout/specs/booking-agent-journey-and-build-plan.md`
- **Existing specs:** `specs/card_post_messages.md`,
  `specs/card_get_messages.md`, `specs/card_agent_chat_page.md`,
  `specs/card_saved_cta.md`, `specs/t4_user_agent_chat_frontend.md`
- **Code that exists today:**
  - `backend/app/routers/agent.py` (queue endpoints, 434 lines, live on T3-user worktree)
  - `backend/app/models/__init__.py` (`BookingsLog`, `AuditLog`)
  - `backend/app/services/authz.py` (`require_permission`, `write_audit_log`)
- **Code that doesn't exist yet:**
  - `backend/app/routers/messages.py` (chat-thread endpoints — spec only)
  - `frontend/app/agent-chat/page.tsx` (chat page — spec only)
  - `frontend/app/saved/page.tsx` updates for the agent CTA (spec only)
  - `frontend/app/admin/agents/page.tsx` (agent dashboard — spec only)
- **Blocker on deploying existing T3-user work:** the alembic chain is
  broken (the `0002_*` migration needs to be renamed to `0006_*` and
  chained to `0005_scraped`). This is the **single biggest
  unblock** before any of the above becomes testable end-to-end on
  the live API.
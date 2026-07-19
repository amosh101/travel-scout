GOAL
Ship the 6 missing user-journey endpoints (auth+profile+GDPR) on the existing v2.1 foundation. Foundation already has register/login/me, intake (Redis landing), itineraries save/list/get/update/delete, search, agent queue. Your scope: the 6 endpoints listed below + 1 consolidation + their tests. Frontend wiring is the next card, NOT this one.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.wt (worktree feat/user-journey — create from main if missing: git worktree add -b feat/user-journey .wt main)
- Stack: FastAPI + SQLAlchemy 2 + Postgres + Next.js 14 (do not change stack)
- Profile: default

ENDPOINTS TO SHIP (all under /api prefix; the v1 API_V1_PREFIX=/api)

1. GET /api/me
   - Returns: {id, email, name, tier, next_billing_date, home_airport, interests[], destinations[], role}
   - Already partially in profile router — check profile.py first, complete if missing
   - Auth: access JWT

2. PATCH /api/me
   - Updatable: name, nationality, passport (encrypted), dob, emergency_contact_name, emergency_contact_phone, home_airport
   - DO NOT allow: email (immutable for v1), tier (admin-only)
   - Audit-log every PATCH

3. POST /api/me/onboarding
   - Body: {home_airport, interests[], destinations[], skippable: bool}
   - Stores into User fields; marks onboarding_complete=true; idempotent (POST same values twice = same result)
   - If skippable=true, stores a flag and onboarding_complete=false
   - 3-step wizard frontend exists (frontend/app/onboarding/page.tsx) — this endpoint is what it POSTs to. Verify the frontend expects this exact shape before changing.

4. POST /api/me/change-password
   - Body: {old_password, new_password}
   - bcrypt verify old, set new, audit log

5. GET /api/me/export (GDPR)
   - Returns: full user JSON dump (profile, itineraries, messages, audit-relevant events)
   - Audit log this access
   - <5s for any user

6. DELETE /api/me (GDPR soft-delete)
   - Sets deleted_at, blocked_at, audit log
   - User can no longer log in
   - Hard purge is a separate cron (out of scope for this card)

CONSOLIDATION (1 task, do it before tests)

- backend/app/routers/itineraries.py has an inline _check_save_quota that duplicates tier_guard.check_tier_limit. Replace the inline check with the canonical tier_guard.check_tier_limit call so the brief's "single TierGuard" is real. Don't change the quota math — only the call site.

AGENT CHAT
- NOT in this card. Out of scope. T4-user owns it.

TESTS (TDD red→green)

backend/tests/test_me_endpoints.py — one file, all 6 endpoints
- happy path for each
- auth failure (no JWT) for each protected route
- soft-deleted user cannot log in / gets 401 on /me
- change-password rejects wrong old
- GDPR export returns 200 + complete user record <5s
- onboarding is idempotent

backend/tests/test_tier_guard_consolidation.py
- itineraries.save() still enforces quota after refactor
- quota math is identical to pre-refactor (same number of saves allowed before 402)

QUALITY BARS
- [ ] pytest backend/tests/test_me_endpoints.py passes
- [ ] pytest backend/tests/test_tier_guard_consolidation.py passes
- [ ] All 6 endpoints in OpenAPI schema at /openapi.json
- [ ] Pydantic schemas in app/schemas/ — do not put request/response models inside router files
- [ ] Every PATCH/DELETE writes to audit_log
- [ ] No mock data — verify against real Postgres or test DB

DONE WHEN
- pytest passes (the new files + the existing suite must not regress)
- 6 endpoints respond on the live server (100.91.143.50:8000)
- Audit log shows entries for PATCH/DELETE/EXPORT
- Commit on feat/user-journey with message 'feat(user): me endpoints + GDPR + tier-guard consolidation'

OUT OF SCOPE (do not touch)
- Agent chat / messaging
- Frontend /profile or /agent-chat pages
- Refresh tokens / logout (document as known gap if you find time)
- Billing UI
- Kiwi/Ticketmaster integration
- Booking-agent router changes (parent of this card is foundation only; booking-agent has its own card)

HARD RULES
- Do not exceed 90 minutes wall-time. If you will run over, block with a clean checkpoint + a comment listing exactly what shipped and what remains.
- Do not modify backend/app/routers/auth.py beyond fixing obvious bugs. New auth endpoints (refresh, logout) are NOT in this card.
- Do not touch frontend code.
- Do not touch admin routers.
- Do not introduce new dependencies without a comment justifying it.
- If you crash or run out of context, the next worker continues from your last commit. Commit early, commit often.

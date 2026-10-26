# Travel-Scout — Three-Persona Product & Engineering Audit
**Date:** 2026-10-21 · **Stack:** FastAPI + Postgres/Redis + Next.js on Hetzner VPS (Tailscale-gated admin)
**Method:** live probes against http://100.91.143.50:8000 / :3000 as all four fixture roles (anon, customer/free, concierge, agent, admin-readonly, superadmin), code citation per finding, DB queries for schema/index/audit facts. No claim below is from memory; every gap carries its evidence.

---

## 1. EXECUTIVE SUMMARY

Travel-Scout's discovery spine is genuinely good and unusually honest: interest-driven matching is deterministic and byte-replicable, events are strictly filtered to selected interests + dated + city-owned, provenance links and coverage notes are user-visible, and the agent hand-off lifecycle (pending → claim → reply → confirmed outcome with price/reference → auto-posted booking summary into the chat thread) works end-to-end — all verified live in this audit. The permission model is real (6 roles, per-endpoint permission guards, real Tailscale CIDR gating), every mutation writes an audit row with before/after, and Stripe's webhook path is signature-verified and idempotent.

The platform is not yet a commerce platform. There is no way to charge anyone: billing is a single webhook route with no checkout-session creation, saved itineraries carry total_price_cents=0, hotels have no prices, flights are key-gated and unconfigured, BookingsLog has no commission/markup field, and nothing delivers a confirmation, voucher, or receipt outside the chat window (no SMTP/Twilio integration exists in the codebase — grep: 0 hits).

**Top 3 risks:**
1. **No payment rail at all** (G-01) — the brief's "payment links to complete bookings" cannot happen; commission tracking is impossible without it.
2. **Double-booking path** (G-02) — re-handoff after a confirmed outcome creates a fresh open queue row on the same itinerary; an agent treating it as new books twice with real money.
3. **No erasure path + no rate limiting** (G-03, G-04) — GDPR Art. 17 noncompliance with passport/nationality/dob stored, and unthrottled auth/search endpoints.

**Verdict:** Not production-ready as a booking platform; production-ready as a personalized discovery + agent-workflow pre-booking product. The gap is commerce, delivery, and isolation — not matching quality.

---

## 2. SCORECARD

Scores 1 (broken/absent) → 5 (excellent). One-line rationale each.

| Dimension | User | Agent | Admin |
|---|---|---|---|
| **A. Simplicity** | **4** — 3-step flow (interests → preview → save), honest 404s with actionable copy, mobile 390px fits all pages (probed); minus: no result filters (G-18), sparse-interest dead end (G-23) | **3** — queue lifecycle + thread replies are clean; minus: no assigned-customer roster (G-10), queue and chat live on separate pages, no bulk actions | **3** — permission-filtered sidebar + real identity header; minus: no taxonomy/booking CRUD (G-08), no staging/preview (G-16), no rollback |
| **B. Performance** | **4** — warm discover 1.5s / cold ~6s (measured), 1h feed + 24h event caches, fail-fast overpass (4s×3 mirrors) | **3** — polling-only sync 8–15s (G-15), queue list is N+1 (G-22), zero DB indexes on hot tables (G-09) | **3** — overview fires 5 APIs + /me on each load; no indexes (G-09); no bulk-edit (G-16) |
| **C. Accuracy** | **3** — deterministic + strictly dated + city-filtered events; minus: no pricing (G-06), date-only venue times (G-12), no cancellation terms (G-07) | **2** — dedupe hole admits second open rows post-confirm (G-02), zero agent isolation (G-05), no commission fields (G-06), provider truth not verified (G-20) | **3** — audit breadth real (300 rows, every action, before/after in user.update), single booking row = one truth; minus: audit log mutability unconfirmed (G-11), no booking/taxonomy editors (G-08), no erasure (G-03) |

---

## 3. GAP REGISTER

Fields per row: ID | Persona(s) | Severity | Category | Description | Evidence | Impact | Recommendation | Effort.

**G-01 | User, Agent | Critical | Accuracy/Commerce** | No payment rail: no checkout session creation, no payment links, no invoices, no refunds; billing is webhook-only (tier flips from subscription invoices). | `openapi`: only `/api/billing/webhook` under billing; saved rows carry `total_price_cents: 0`; `/saved` MVP note ("bookings go to Google Flights… no commission yet"); `grep refund|checkout` in billing.py: no checkout/refund code. | The brief's core promise (customer completes booking via link) cannot execute; agent reconciliation impossible; revenue cannot be collected. | Stand up hosted Stripe Checkout Sessions (PCI stays off-platform): per-booking checkout for self-pay customers; per-handoff invoice link for agent-pay; on `invoice.paid` reconcile the BookingsLog row; expiry + retry via Stripe's hosted flow. | **L**

**G-02 | Agent, User | Critical | Accuracy** | Double-booking hole: hand-off dedupe only inspects `pending/claimed/in_progress`; a confirmed (or failed) row does not block a second open hand-off on the same itinerary. | `agent.py:188–194` — `status.in_(("pending", "claimed", "in_progress"))`. | Agent sees a "new" pending row for an already-confirmed booking and books again with real money; no UI cue distinguishes it from the prior confirmed row. | Include prior row state in hand-off response (409 with the confirmed row's amount/reference); add a partial unique index on active bookings per itinerary; show prior outcomes on the hand-off card. | **S**

**G-03 | User, Admin | Critical | Compliance** | No data-erasure path; users store passport_expiry, nationality, date_of_birth, phone. Export exists; erasure does not. | `openapi`: `/api/me/export`, `/api/profile/me/export` — no delete/erase route; User model columns (models `passport_expiry`, `date_of_birth`, `nationality`); erasure of test fixtures in this workspace required manual `psql DELETE`. | GDPR Art. 17 (and POPIA analogue) non-compliance; erasure currently requires DB surgery with audit-log integrity as collateral. | Add `DELETE /api/me` (soft → pseudonymise; keep audit rows, strip PII from metadata blobs), admin-initiated erasure with `user.block`-style audit; document retention windows. | **M**

**G-04 | All | High | Security** | No rate limiting anywhere; no login lockout/failed-attempt tracking. | `grep slowapi|Limiter|rate_limit` in backend: 0 functional hits; `auth.py` has no failed_attempts/lockout logic; discover endpoint performs outbound source calls per request (cached 1h/24h softens but first hits are expensive). | Credential stuffing on login; cost amplification through discover; webhook abuse is mitigated by signature verification. | slowapi-style buckets: login 5/min/IP+account, discover 10/min/user, register 3/min/IP; exponential backoff + audit on lockout. | **M**

**G-05 | Agent, User | High | Security** | Agent data isolation = none: any `agent.work` holder reads every customer's thread, every saved itinerary, and the hand-off brief including nationality, passport expiry, DOB. | `messages.py:_ensure_itinerary_visible` — agents pass the ownership filter for ALL itineraries; `get_hand_off_brief` returns `user_nationality`, `user_passport_expiry`, `user_dob` to any agent; thread index returns all owners' emails. | Cross-customer PII exposure between agents; least-privilege violated; a dispute between agents or an audit would show unrestricted browsing. | Assignment-scoped visibility: claimed/mine + unclaimed pool for the queue; thread reads gated by `assigned_agent_id` (or claim-to-open); PII fields released only to the claiming agent. | **M**

**G-06 | User, Agent, Admin | High | Accuracy/Commerce** | Pricing integrity absent end-to-end: no taxes/fees, no currency conversion (saved rows hardcode USD at 0), no commission/markup fields on bookings, no reconciliation between the customer's view and the agent's recorded amount. | SavedItinerary payload `total_price_cents=0`, `currency="USD"` (save path); BookingsLog columns (from router/schemas) have `amount_cents`/`currency`/`external_id` only — no `commission_cents`, `markup_pct`, `payment_status`; hotels = Overpass POIs with no price; flights = `kiwi_not_configured`. | The rubric's "totals reconcile across three personas" is unevaluable; agent amounts are self-declared with no cross-check; margin invisible to admin. | Add `commission_cents`, `markup_pct`, `payment_status`, `paid_at` to BookingsLog (migration); require amount + commission on `confirmed` outcomes; admin reconciles against the payment event. | **M** (fields) / **L** (with pricing)

**G-07 | User | High | Accuracy** | No out-of-app delivery: no email/SMS anywhere; confirmations, vouchers, receipts exist only as in-app chat cards; no cancellation terms surfaced anywhere. | `grep smtp|sendgrid|twilio|resend|postmark|mailgun` in backend/app: 0 hits; confirmation UX = the in-thread `is_summary` card; `grep cancel` in booking flows: nothing. | A customer who doesn't open the app never learns the booking state; no paper trail for support/disputes; terms never accepted. | Transactional email (SES/Postmark) on outcome/summary/refund; cancellation-terms block in the summary card; downloadable voucher PDF per confirmed booking. | **M**

**G-08 | Admin | High | Accuracy** | Admin CRUD incomplete: can edit users, roles, weights, source flags; cannot edit booking records, saved itineraries, or the interest taxonomy. | `openapi` admin routes: users(+roles), weights, sources, audit, (queue/messages read via agent/itinerary perms); no interests/destinations/queue-write endpoints; taxonomy changes = seed scripts only. | "Edit any detail of any menu/persona/content" unmet; correcting a mis-typed booking amount requires DB surgery; catalog updates need a deploy. | `PATCH /api/admin/queue/{id}` (amount/reference/status with audit + before/after), itinerary notes/title patch, taxonomy CRUD (`interest.admin` permission already exists). | **M**

**G-09 | All | High | Performance** | No explicit indexes on hot tables: `saved_itineraries`, `messages`, `bookings_log`, `user_interests` have zero named indexes beyond PK/FK/unique defaults. | `pg_indexes` for those tables filtered for `idx%`: empty set. | Thread lookups by `itinerary_id`, queue by `status+created_at`, profile interests by `user_id` all seq-scan; fine at 72 users, degrades with consoles polling every 8–15s. | Migration: `messages(itinerary_id)`, `bookings_log(status, created_at)`, `saved_itineraries(user_id, created_at)`, `user_interests(user_id)`. | **S**

**G-10 | Agent | High | Simplicity** | No customer roster: agents cannot see "their" customers or browse a customer's saved trips; `/admin/users` (their `user.read`) lists ALL platform users unserviced. | Role-permission map: Agent = `{agent.work, user.read}`; admin_users GET returns the full user list; no "assigned customers" surface exists. | Post-outcome continuity is lost; agents reconcile from memory; listing all users to an agent over-shares identities. | "My customers" tab: users with queue rows claimed by the agent + their threads; move raw `user.read` off the Agent role if not otherwise needed. | **M**

**G-11 | Admin | High | Security/Accuracy** | Audit trail not provably immutable; no rollback or draft/publish for admin edits; taxonomy unversioned. | No triggers/grants seen protecting `audit_log` (UPDATE/DELETE not blocked at the DB level as far as schema review shows); weights/sources PATCH = instant prod effect, no diff preview; Interest rows have no version column. | A compromised or careless admin can rewrite history silently; bad weight changes propagate immediately. | Append-only trigger + `REVOKE UPDATE, DELETE` for the app role on audit_log; draft/publish columns with diff preview for weights/sources; version rows for taxonomy edits. | **M**

**G-12 | User | Medium | Accuracy** | Event/trip times are date-only with no venue-timezone logic: events carry dates (no local time), anchors take naive ISO dates; the DB already stores per-city `timezone`. | Discover contract consumes `YYYY-MM-DD` anchors; EventRecord = date-granular; `cities.timezone` column exists (schema) but is unused by the event window. | A ±1 day boundary mistake puts an event outside/inside the trip window for long-haul trips; day planning off by hours. | Attach city tz to events; normalize anchors to tz-aware instants at save; display local dates in the itinerary. | **M**

**G-13 | User | Medium | Accuracy** | Single-origin, single-destination only; no multi-city, layover, or regional routing. | Discover contract: one `destination_override`; route = one OSRM leg; saved payload carries one destination. | Regional trips (Maputo → Johannesburg → Cape Town) unsupported; the rubric expects it (scope ambiguous — see Open Questions). | If in scope: multi-stop model (destinations list, per-leg routes/hotels, combined score) — significant engine work. | **L**

**G-14 | All | Medium | Simplicity** | Terminology drift: "My saved trips" (nav) vs "YOUR TRIPS" (agent-chat) vs "Suggested trips"; customers say "Contact booking agent", console says "hand-off"; "Conversations" vs "chat". | Header/nav text across pages (live browser passes). | Raises cognitive load below the rubric's bar; hurts cross-persona training. | Terminology table + single vocab (itinerary/trip, conversation, hand-off) applied across surfaces. | **S**

**G-15 | User, Agent | Medium | Performance** | No real-time channel: both consoles poll (8–15s); a fast exchange lags and may double-reply. | `setInterval(load, 10000)` / `15000` in admin/messages + admin/queue (code, verified). | Wasted replies, awkward pauses; the "real-time sync" rubric line unmet. | SSE (simple, fits the stack) or websocket per thread+queue; fall back to polling. | **M**

**G-16 | Admin | Medium | Simplicity** | No staging/preview/bulk ops: weight and source changes hit production instantly; no list-edit batches. | `PATCH /api/admin/weights/{key}` + `/api/admin/sources/...` = immediate effect; no dry-run flag in the router; no bulk endpoints. | A wrong weight silently re-ranks production results; taxonomy mistakes are deployment-coupled. | draft/apply with diff preview (ties to G-11); bulk actions on users/sources (selected rows). | **M**

**G-17 | User | Medium | Accuracy** | Honest sparsity: interests outside the current news cycle return genuinely dated events only — which can be zero (jazz + city, current window). | Live behavior: sparse-interest anonymous preview → 404 with actionable copy; coverage notes show feed skips (e.g. "reviewed 172 items… 0 off-interest"). | Correct by design (no fabrication rule) but conversion suffers; the rubric's "false negatives" axis. | Add per-city structured JSON-LD sources (e.g. venue/commercial listing pages) under the probe-then-wire rule; "notify me when dated events appear" capture on the 404 state. | **M/L**

**G-18 | User | Medium | Simplicity** | Interest capture is one-dimensional: catalog keys without sub-preferences or result filters (no evening-only, no price, no distance filters on results). | Onboarding pill selection only; /itineraries render fixed result set with no filter UI (page code). | Granularity below the rubric ("intuitive and granular enough"); users can't narrow a broad interest. | Result-page filters (dates, distance-from-venue, event kind — `kind` tags already exist server-side); optional per-interest sub-tags in the intake. | **M**

**G-19 | All | Medium | Security** | Session tokens are long-lived JWTs in localStorage; no refresh/rotation/revocation. | `travel_scout_token` in localStorage (auth-context); openapi auth = login/register/me only (no refresh/logout-revoke); token survives until expiry. | XSS-stolen tokens persist; no device-session revocation; logout = local delete only. | Short-lived access + httpOnly refresh cookie + server-side revocation list; logout hits the API. | **M**

**G-20 | Agent, Admin | Medium | Accuracy** | Provider truth not verified: booking status consistency is strong inside the platform (single BookingsLog row), but there is no provider webhook/pull to detect later cancellations made outside. | BookingsLog has `external_id` (free text) only; no provider integration or reopen flow after `confirmed`. | Platform can show confirmed while the provider records a cancellation; reconciliation drift invisible until the customer complains. | Reopen/outcome-amendment flow with audit; when a provider API exists, pull status; periodic manual-reconciliation report for admin. | **M**

**G-21 | All | Low | Simplicity** | N+1 in the queue list loader: for each row the handler issues 2 extra SELECTs (user + itinerary). | `agent.py:_row_to_queue_item` — per-row executes for User and SavedItinerary. | At 200 queue rows = 400 extra queries per poll; imperceptible today, wasteful tomorrow. | Batch-fetch users+itineraries with IN() and zip (one-round-trip fix). | **S**

**G-22 | User | Low | Simplicity** | Sparse-interest anonymous dead end lacks lead capture: the honest 404 advises alternatives but cannot notify when dated events appear. | Live 404 state copy (browser-probed). | Lost prospective users for slow interest/destination combos. | Optional email capture on the 404 → background job re-runs the interest query and mails when non-empty (needs G-07's email). | **S**

**G-23 | All | Low | Simplex/A11y** | Accessibility pass not done: buttons are real buttons (good), but no aria-labels on icon-only controls, no skip links, no form error summaries; no automated a11y sweep. | Code review only — no axe/lighthouse audit run in this review. | WCAG gaps unknown; Sir's team tests on iPhones (positive evidence: 390px fits + probe). | Run axe-core CLI over the five core pages; fix the top-10 violations; add skip links + error summaries. | **S/M**

**G-24 | All | Low | Accuracy** | Dedupe of the same event across sources covers (title, date, city) but anchor-vs-suggested overlap can double-show (holiday as both context and event when an interest matches). | Free-events aggregator dedupe (verified) + result payload carrying the same holiday in two sections in some live responses. | Minor noise; no monetary effect. | One canonical event list in the response; sections reference IDs. | **S**

---

## 4. IMPROVEMENT ROADMAP

**NOW (0–2 weeks) — close the money-safety and integrity holes**
1. G-02 (S) — dedupe/constraint: no second open hand-off on a confirmed itinerary. *(accuracy)*
2. G-09 (S) + G-21 (S) — hot-table indexes + queue N+1 fix. *(performance)*
3. G-04 (M) — rate limiting + login lockout. *(security)*
4. G-03 (M) — self-service erasure with pseudonymisation + audit-preserving delete. *(compliance)*
5. G-01 (scoping decision) — choose the payment model (Open Questions Q2) and stand up hosted Stripe Checkout; unblocks G-06. *(commerce spine)*

**NEXT (2–6 weeks) — commerce fields, delivery, isolation, admin CRUD**
6. G-06 (M) — commission/markup/payment_status fields + mandatory amount on confirm. *(accuracy)*
7. G-07 (M) — transactional email on outcome/summary; cancellation-terms block; voucher PDF. *(accuracy/simplicity)*
8. G-05 (M) — assignment-scoped agent visibility; PII released on claim. *(security)*
9. G-08 (M) — admin CRUD for bookings + taxonomy (permission keys already exist). *(simplicity)*
10. G-10 (M) — agent customer roster. *(simplicity)*
11. G-11 (M) — immutability + draft/apply. *(security)*
12. G-19 (M) — refresh/rotation/revocation. *(security)*

**LATER (6+ weeks) — depth and polish**
13. G-12 (M) — venue-timezone event times. *(accuracy)*
14. G-15 (M) — SSE real-time thread/queue sync. *(performance/simplicity)*
15. G-16 (M) — bulk ops + diff preview across admin surfaces. *(simplicity)*
16. G-17 expansion (M/L) — per-city structured event sources (probe-then-wire each). *(accuracy)*
17. G-18 (M) — result filters + sub-preference tags. *(simplicity)*
18. G-23 (S/M) — axe sweep + fixes. *(a11y)*
19. G-13 (L) — multi-city model if stakeholder-confirmed in scope. *(accuracy)*

---

## 5. OPEN QUESTIONS

1. **Scope of multi-city/layover routing (G-13):** the rubric lists it; the engine is single-leg by design. Build it, or declare single-city-plus-daytrips the product boundary?
2. **Who owns the money (G-01/G-06):** platform checkout (platform = merchant of record) vs agent-pay (agent = merchant, platform records)? Chargeback/refund ownership and PCI posture differ fundamentally — this decision gates the whole commerce spine.
3. **Commission model (G-06):** flat %, agent-set markup with admin caps, or per-deal? Is agent commission visible to the customer or internal?
4. **Delivery provider + trigger list (G-07):** SES vs Postmark (or Zoho, given the region); do we message on handoff received, outcome confirmed, refund, or reminders only? Are Mozambique numbers SMS-worthy (register collects phone today, unused)?
5. **Agent workforce shape (G-05):** open pool with claim-races (current) vs dispatch-to-one-agent? Determines whether isolation is by assignment or by dispatch policy.
6. **Data residency (G-03):** GDPR applies to EU customers; Mozambique customers → POPIA-like duties. Single policy (GDPR-grade) for simplicity?
7. **Taxonomy editability + versioning (G-08/G-11):** does Sir edit interest catalogs in production (needs CRUD + versions), or are catalogs changed by engineering with seeds?
8. **Mobile:** the responsive web passes a 390px probe on the three key consoles — is a native/PWA wrapper expected, or mobile-web only?
9. **Provider integrations for "provider truth" (G-20):** none are wired; is manual external_id + periodic admin reconciliation acceptable for the current volume?

---

## Recognition (brief, per the brief's request)
The engine layer deserves credit: byte-replicable results (verified deep-equal twice), strict interest/city/date filtering with zero off-interest leaks (verified live), honest coverage notes rendered to all three personas, a race-safe claim lifecycle with audit rows on every transition, a working booking-summary card auto-posted on confirm, real permission separation that survives a browser check (admin-readonly saw zero ways to write), and a mobile-usable console at 390px. The foundations are the kind that commerce can be built on — once the spine in G-01 exists.
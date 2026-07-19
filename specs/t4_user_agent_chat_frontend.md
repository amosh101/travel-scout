GOAL
Ship the agent-chat API + the 3 frontend pages that the v2.1 foundation is missing. Foundation has the agent queue + agent router scaffolding but no message endpoints and no real /profile, /agent-chat, /saved-with-agent-CTA pages.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.wt (worktree feat/user-journey — same as T3-user)
- Profile: default

BACKEND (agent chat API)

1. POST /api/messages
   - Body: {itinerary_id, body}
   - Concierge-only (tier guard: 403 if user.tier != 'concierge')
   - Appends to message thread for that itinerary
   - Auto-assigns to the user's assigned agent (look up from agent_assignments table; if none, use the least-loaded active agent)
   - Returns the created message with id, created_at, sender_role

2. GET /api/messages?itinerary_id=<id>&since=<iso>
   - Concierge-only OR owner-only (the user who owns the itinerary can read their own thread)
   - Returns messages ordered by created_at ASC
   - 'since' param enables polling (3s interval from frontend)
   - Empty array if no messages

3. Pydantic schemas in app/schemas/messages.py
4. Audit log on POST (sender, action='message_sent', target=itinerary_id)

FRONTEND (3 pages, /profile is the most important)

1. /profile (frontend/app/profile/page.tsx) — REAL edit page
   - GET /api/me on load
   - Editable: name, nationality, passport, dob, emergency contact, home_airport
   - "Change password" inline form (calls POST /api/me/change-password)
   - "Export my data" button → GET /api/me/export → download JSON
   - "Delete my account" button (double-confirm) → DELETE /api/me
   - Tier badge + "Manage billing" link to /billing (out of scope but link should work)
   - Theme: black-responsive, matches existing /onboarding style

2. /agent-chat (frontend/app/agent-chat/page.tsx) — concierge only
   - List of user's itineraries with active message threads
   - Click an itinerary → thread view, polling every 3s
   - Post a message at the bottom
   - Redirect to /onboarding or /itineraries if user.tier != 'concierge'
   - Theme: black-responsive

3. /saved (frontend/app/saved/page.tsx) — already exists, add agent CTA + outbound link
   - "Message my agent" button visible if user.tier == 'concierge' AND booking_state == 'requested' or 'saved'
   - "Open booking link" CTA when itinerary has outbound_url (free+ tiers)
   - Don't break existing /saved list behaviour

TESTS

backend/tests/test_messages.py
- POST /api/messages as concierge user: 201 + message in thread
- POST as free/limited/unlimited: 403
- GET /api/messages returns chronological list
- 'since' filter works (only newer messages)
- audit log entry on POST

frontend tests (vitest or jest — check existing setup; skip if not configured)
- Skip frontend unit tests if the project doesn't already have them. Time budget is tight.

QUALITY BARS
- [ ] pytest backend/tests/test_messages.py passes
- [ ] curl smoke test on the 2 message endpoints works on the live server
- [ ] /profile loads + saves changes
- [ ] /agent-chat shows the concierge message thread (even with 0 messages)
- [ ] /saved concierge CTA shows for concierge users, hidden for free users

DONE WHEN
- pytest passes (the new file + existing suite must not regress)
- 3 frontend pages exist, render without console errors
- Commit on feat/user-journey with message 'feat(user): agent-chat api + /profile + /agent-chat + /saved CTA'

OUT OF SCOPE
- Real-time websockets (polling is fine for v1)
- File attachments
- Read receipts
- Agent-side message UI (that lives in T3-admin/T4-admin)
- Push notifications

HARD RULES
- Do not exceed 90 minutes wall-time.
- Do not modify the backend tier-guard, schemas, or any non-message router.
- Do not add a new top-level page beyond the 3 listed.
- If a page already exists (e.g. /saved is partial), extend it — don't fork.

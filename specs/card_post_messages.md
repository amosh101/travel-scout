GOAL
POST /api/messages — concierge-only send. ONE endpoint, ONE test file, commit. No exploration.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.user4
- Branch: wt/t4-user
- Create the worktree if missing: cd /root/.hermes/workspace/projects/travel-scout && git worktree add -b wt/t4-user ../travel-scout.user4 main

EXISTING HELPERS — REUSE, DO NOT REINVENT
- get_current_user: app.security.get_current_user (use grep to find it)
- Itinerary model: app.models.SavedItinerary (or similar — grep for the class)
- Message model: may not exist yet — check the migrations or grep for 'class Message'. If missing, add a minimal SQLAlchemy model in app/models/__init__.py with fields: id, itinerary_id, sender_user_id, body, created_at, sender_role (user/agent). + add a migration in backend/migrations/versions/. Do this FIRST as a separate commit, then the endpoint.
- Tier guard: app.services.tier_guard.require_tier('concierge') — check its API first
- Audit log: from app.services.audit import write_audit_log

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/messages.py (CREATE), backend/app/schemas/messages.py (CREATE), backend/tests/test_messages_post.py (CREATE), backend/app/main.py (5 lines max change to mount), backend/app/models/__init__.py (only to add Message class if missing), backend/migrations/versions/0002_message.py (CREATE if Message model added)
- DO NOT touch any existing endpoint
- DO NOT install new packages
- Time budget: 25 minutes. Commit at 20 min and BLOCK.

THE ENDPOINT
POST /api/messages
- Auth: Depends(get_current_user) + require_tier('concierge')
- Body: {itinerary_id: UUID, body: str (max 4000)}
- Verifies the user owns the itinerary (or is the assigned agent)
- Auto-assigns to the user's assigned agent (or least-loaded active agent)
- Appends a Message row
- Audit log: action='message_sent', target=itinerary_id
- 201 on success, 401 no auth, 403 not concierge, 404 not owner

ROUTER
- File: backend/app/routers/messages.py (CREATE)
- Mount in app/main.py with the other routers (5 lines max change)

SCHEMA
- File: backend/app/schemas/messages.py (CREATE)
- MessageIn, MessageOut

TEST FILE
- File: backend/tests/test_messages_post.py (CREATE)
- 4 tests: concierge happy path (create user, create itinerary, post message, verify row), free tier 403, not-owner 404, audit log written

DONE WHEN
- All 4 tests pass
- Committed: 'feat(user): POST /api/messages'

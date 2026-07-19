GOAL
Ship the user management + agent management + admin itinerary views on top of the foundation's existing admin scaffolding. Foundation has admin_audit.py, admin_sources.py, admin_users.py, admin_weights.py mounted — your scope: complete the user CRUD + add agent CRUD + admin itinerary view.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.wt (worktree feat/admin-journey — already exists at /root/.hermes/workspace/projects/travel-scout.wt, branch feat/admin-journey)
- Profile: default

ENDPOINTS (extend admin_*.py, do not create new admin files)

1. GET /api/admin/users
   - Query: search (email/name), tier, blocked, page (default 1)
   - Returns: paginated list with id, email, name, tier, blocked_at, created_at, last_login_at
   - Already partial in admin_users.py — complete it

2. GET /api/admin/users/<id>
   - Full record + last 50 audit events for that user
   - 404 if not found

3. POST /api/admin/users
   - Create user with admin-generated invite link
   - Returns: {id, invite_url, expires_at}
   - Invite link is signed JWT with 7-day expiry, single-use

4. POST /api/admin/users/<id>/block
   - Sets blocked_at, audit
   - Cannot block self

5. POST /api/admin/users/<id>/unblock
   - Clears blocked_at, audit

6. POST /api/admin/users/<id>/impersonate
   - Returns: read-only access token, audit, expires 1h
   - Token cannot write, can only read

7. CSV export on GET /api/admin/users (Content-Type: text/csv)

AGENTS

8. GET /api/admin/agents
   - List with current workload (open itineraries count), SLA hit rate (last 30d), suspended flag, max_active capacity

9. POST /api/admin/agents
   - Create agent account (similar invite-link flow)

10. POST /api/admin/agents/<id>/suspend, /reactivate, PATCH /<id>/capacity (max_active)

ITINERARIES (admin view)

11. GET /api/admin/itineraries
    - Query: user_id, state (saved/requested/booked/unavailable), page
    - Returns paginated list with user_email, event title, booking_state, agent_name, saved_at

12. GET /api/admin/itineraries/<id>
    - Full record + agent notes + message thread (read-only)

13. PATCH /api/admin/itineraries/<id>
    - Edit notes, reassign agent_id, force booking_state (with reason)
    - Audit all changes

14. POST /api/admin/itineraries/<id>/reassign
    - Body: {agent_id, reason}
    - Audit

FRONTEND

- /admin/users (frontend/app/admin/users/page.tsx) — list + block/unblock + invite + impersonate
- /admin/agents (frontend/app/admin/agents/page.tsx) — list + suspend/reactivate + capacity slider
- /admin/itineraries (frontend/app/admin/itineraries/page.tsx) — list + detail drawer + reassign
- Check what already exists. Extend, don't fork.

TESTS

backend/tests/test_admin_users.py
backend/tests/test_admin_agents.py
backend/tests/test_admin_itineraries.py
- happy path for each endpoint
- non-admin gets 403
- self-block is rejected
- impersonation token cannot write
- reassign updates the agent_assignments table
- audit log entries on every state change

QUALITY BARS
- [ ] pytest passes
- [ ] All admin routes mounted in app/main.py
- [ ] /admin/users renders user list (or 404 → next card will add it)
- [ ] Every action writes to audit_log

DONE WHEN
- pytest passes
- Live server has all 14 admin endpoints responding (admin auth required)
- /admin/users, /admin/agents, /admin/itineraries pages render
- Commit on feat/admin-journey with 'feat(admin): users + agents + itineraries'

OUT OF SCOPE
- Interests catalog CRUD (T4-admin)
- Data sources manager (T4-admin)
- Algorithm weights (T4-admin)
- Reports/audit viewer pages (T4-admin)

HARD RULES
- 90 min wall-time budget
- Do not touch user-facing routers
- Do not add new admin files — extend the existing admin_*.py
- Admin role check via require_permission('admin.access') — verify it's already wired

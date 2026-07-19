GOAL
admin: GET /api/admin/itineraries + GET/PATCH/POST reassign. 4 endpoints, 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin3
- Branch: wt/t3-admin
- Same worktree

EXISTING HELPERS
- Itinerary model: SavedItinerary or similar
- Booking states: saved / requested / in_progress / booked / unavailable / closed
- Agent assignment: assigned_agent_id field on SavedItinerary (grep 'assigned_agent')

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_itineraries.py (CREATE), backend/app/schemas/admin_itineraries.py (CREATE), backend/tests/test_admin_itineraries.py (CREATE), backend/app/main.py (5 lines max)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINTS
GET /api/admin/itineraries?user_id=&state=&page=
- Auth: admin
- Returns: {items: [{id, user_email, event_title, booking_state, agent_name, saved_at}, ...], total, page, per_page}

GET /api/admin/itineraries/<id>
- Returns: full itinerary + agent notes + message thread (read-only, latest 50 messages)

PATCH /api/admin/itineraries/<id>
- Body: {notes?, booking_state?, event_id?, flights?}
- Updates the itinerary. If booking_state is forced (admin override), require 'reason' field.
- Audit: action='itinerary_edited', metadata={changes}

POST /api/admin/itineraries/<id>/reassign
- Body: {agent_id, reason}
- Updates assigned_agent_id
- Audit: action='itinerary_reassigned', metadata={old_agent, new_agent, reason}

ROUTER
- File: backend/app/routers/admin_itineraries.py (CREATE)
- Mount in main.py

SCHEMA
- File: backend/app/schemas/admin_itineraries.py (CREATE)
- AdminItineraryOut, AdminItineraryPatchIn, AdminReassignIn

TEST FILE
- File: backend/tests/test_admin_itineraries.py (CREATE)
- 4 tests: list filtered by state, detail returns notes+messages, patch with reason updates booking_state, reassign changes agent_id

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): itineraries list/detail/patch/reassign'

GOAL
GET /api/messages — polling thread read. ONE endpoint, ONE test file, commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.user4
- Branch: wt/t4-user
- Same worktree as POST /api/messages (created by previous card)

EXISTING HELPERS
- All from POST /api/messages
- 'since' filter: query param, ISO 8601, returns only messages with created_at > since

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/messages.py (EXTEND, do not re-touch main.py), backend/app/schemas/messages.py, backend/tests/test_messages_get.py (CREATE)
- Time budget: 15 minutes

THE ENDPOINT
GET /api/messages?itinerary_id=<id>&since=<iso>
- Auth: Depends(get_current_user)
- Owner-only OR concierge assigned to the itinerary
- Returns messages ordered by created_at ASC
- 'since' is optional ISO 8601, filters out older messages
- Empty list if no messages
- 200 on success, 401, 403, 404

ROUTER
- File: backend/app/routers/messages.py (EXTEND)
- Add the GET handler below the POST

TEST FILE
- File: backend/tests/test_messages_get.py (CREATE)
- 4 tests: chronological order (post 2 messages, GET returns both in order), since filter works (post 2, GET with since=first.created_at returns only second), non-owner 403, empty list (no messages posted, GET returns [])

DONE WHEN
- All 4 tests pass
- Committed: 'feat(user): GET /api/messages'

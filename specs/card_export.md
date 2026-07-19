GOAL
GET /api/me/export — GDPR JSON dump. ONE endpoint, ONE test file, commit. No exploration, no extra changes.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.user3 (worktree on branch wt/t3-user)
- Already created by the PILOT card. cd into it.

EXISTING HELPERS — REUSE, DO NOT REINVENT
- get_current_user dependency: app.security.get_current_user
- User model: app.models.User
- Pydantic base: from pydantic import BaseModel (or whatever the project uses — check schemas.py head once)
- Test fixtures: backend/tests/conftest.py (read ONCE on first use, then never re-read)
- Audit log: from app.services.audit import write_audit_log (use it for any state change)

HARD RULES (each is a fatal mistake)
- DO NOT cat files larger than 50 lines. Use head, tail, grep, search_files, wc -l.
- DO NOT touch any router other than profile.py
- DO NOT modify models, security, audit, tier_guard, authz, main.py, or migrations
- DO NOT install new packages
- DO NOT add a new database column
- DO NOT change the User or any other model
- If you need to make a change outside profile.py + the new test file, BLOCK with a comment
- Time budget: 15 minutes wall time. Commit what you have at 12 min and BLOCK.


THE ENDPOINT
GET /api/me/export
- Auth: Depends(get_current_user)
- Returns: full user JSON dump including profile, itineraries, messages
- Audit log: action='gdpr_export'
- Must respond in <5s
- Content-Type: application/json
- Content-Disposition: attachment; filename="user-<id>-export.json"

ROUTER CHANGES
- File: backend/app/routers/profile.py
- Aggregate: user row, all saved_itineraries, all messages where sender or recipient, audit-relevant events

TEST FILE
- File: backend/tests/test_me_export.py
- Tests:
  1. test_export_returns_user_record — 200, JSON has user fields
  2. test_export_includes_itineraries — saved one → export has it
  3. test_export_writes_audit — assert audit row
  4. test_export_requires_auth — 401

DONE WHEN
- All 4 tests pass
- Export <5s in tests
- Committed: 'feat(user): GET /api/me/export'


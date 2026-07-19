GOAL
DELETE /api/me — GDPR soft delete. ONE endpoint, ONE test file, commit. No exploration, no extra changes.

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
DELETE /api/me
- Auth: Depends(get_current_user)
- Sets user.deleted_at = now(), user.blocked_at = now()
- Audit log: action='gdpr_delete'
- 204 on success, 401 on no auth
- After deletion: user cannot log in (login must check deleted_at and return 401)

ROUTER CHANGES
- File: backend/app/routers/profile.py (the DELETE handler)
- File: backend/app/routers/auth.py (extend the login handler to reject soft-deleted users — ONLY the login branch, not anything else)

TEST FILE
- File: backend/tests/test_me_delete.py
- Tests:
  1. test_delete_me_soft_deletes — DELETE → 204, GET /me → 401
  2. test_deleted_user_cannot_login — login with same creds → 401
  3. test_delete_writes_audit — assert audit row
  4. test_delete_requires_auth — no JWT → 401

DONE WHEN
- All 4 tests pass
- Committed: 'feat(user): DELETE /api/me (GDPR soft delete)'


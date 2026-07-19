GOAL
POST /api/me/change-password — bcrypt verify + set. ONE endpoint, ONE test file, commit. No exploration, no extra changes.

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
POST /api/me/change-password
- Auth: Depends(get_current_user)
- Body: {old_password: str, new_password: str (min 8)}
- bcrypt verify old, set new, audit log
- 204 on success, 401 on no auth, 400 if old_password wrong, 422 on bad new

PYDANTIC SCHEMA
- File: backend/app/schemas/me.py
- Add: ChangePasswordIn (old + new)

ROUTER CHANGES
- File: backend/app/routers/profile.py

TEST FILE
- File: backend/tests/test_me_change_password.py
- Tests:
  1. test_change_password_happy_path — old correct, new set, login with new works
  2. test_change_password_wrong_old — 400
  3. test_change_password_short_new — 422 (Pydantic min_length)
  4. test_change_password_requires_auth — 401

DONE WHEN
- All 4 tests pass, login with new password works
- Committed: 'feat(user): POST /api/me/change-password'


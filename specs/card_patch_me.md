GOAL
PATCH /api/me — update user profile. ONE endpoint, ONE test file, commit. No exploration, no extra changes.

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
PATCH /api/me
- Auth: Depends(get_current_user)
- Body: {name?, nationality?, passport?, dob?, emergency_contact_name?, emergency_contact_phone?, home_airport?}
- Updates the user row. Email and tier are NOT updatable here.
- Audit log: action='profile_update', metadata=updated fields
- 200 on success, 401 on no auth, 422 on bad body

PYDANTIC SCHEMA
- File: backend/app/schemas/me.py (EXTEND, the schema file was created by the PILOT)
- Add: MePatch (all fields optional, with constraints)
- Add: MeOut stays the same as PILOT

ROUTER CHANGES
- File: backend/app/routers/profile.py
- Add the PATCH /me handler. Reuse existing Pydantic models.

TEST FILE
- File: backend/tests/test_me_patch.py (CREATE)
- Tests:
  1. test_patch_me_updates_name — PATCH name → 200 → next GET /me returns new name
  2. test_patch_me_rejects_email_change — PATCH email → 422
  3. test_patch_me_requires_auth — no JWT → 401
  4. test_patch_me_writes_audit_log — assert audit row written with action='profile_update'

DONE WHEN
- All 4 tests pass
- The endpoint returns 200 with the updated user
- Committed: 'feat(user): PATCH /api/me'


GOAL
POST /api/me/onboarding — 3-step wizard store. ONE endpoint, ONE test file, commit. No exploration, no extra changes.

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
POST /api/me/onboarding
- Auth: Depends(get_current_user)
- Body: {home_airport: str, interests: list[str], destinations: list[str], skippable: bool = false}
- Stores into User fields (home_airport, interests JSON, destinations JSON)
- Sets onboarding_complete=true unless skippable=true
- Idempotent: calling twice with same values is fine
- 200 on success, 401 on no auth, 422 on bad body
- Audit log: action='onboarding_completed' or 'onboarding_skipped'

PYDANTIC SCHEMA
- File: backend/app/schemas/me.py
- Add: OnboardingIn (the body), OnboardingOut (the response — same as MeOut)

ROUTER CHANGES
- File: backend/app/routers/profile.py
- Add POST /me/onboarding handler

TEST FILE
- File: backend/tests/test_me_onboarding.py
- Tests:
  1. test_onboarding_stores_fields — POST stores home_airport/interests/destinations, GET /me returns them
  2. test_onboarding_is_idempotent — POST twice, no error
  3. test_onboarding_skippable — skippable=true → onboarding_complete=false
  4. test_onboarding_requires_auth — no JWT → 401

DONE WHEN
- All 4 tests pass
- Committed: 'feat(user): POST /api/me/onboarding'


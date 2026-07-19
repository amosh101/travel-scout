GOAL
Add ONE endpoint to the existing v2.1 backend: GET /api/me. That's it. Return the current user, their tier, and the next billing date. Write the test. Verify it works. Commit.

READ FIRST (do NOT cat the whole file — just check existence with `ls` or `wc -l`)
- backend/app/routers/profile.py (already exists, may already have a stub)
- backend/app/models/__init__.py (use search_files for 'class User' to find the line)
- backend/app/schemas.py OR backend/app/schemas/*.py (use ls first)
- backend/app/security.py (just to see the get_current_user dependency)
- backend/app/main.py (to see how routers are mounted — don't change this)
- backend/tests/conftest.py (read ONCE for the existing fixtures)

DO NOT READ MORE THAN 50 LINES OF ANY FILE. Use grep / search_files / wc -l to navigate. The codebase is large and your context is limited.

WORKSPACE
- Worktree: /root/.hermes/workspace/projects/travel-scout.user3
- Branch: wt/t3-user (create with: git worktree add -b wt/t3-user ../travel-scout.user3 main)
- Run from that path. All edits committed there.

EXISTING HELPERS — DO NOT REINVENT
- get_current_user dependency already exists in app.security — use it
- User model already has: id, email, name, tier, home_airport, created_at, deleted_at
- Subscription model has: tier, current_period_end (this is the next_billing_date)
- Audit log helper: from app.services.audit import write_audit_log

THE ENDPOINT

GET /api/me
- Auth: require current user via Depends(get_current_user)
- Returns: {
    id: str (uuid),
    email: str,
    name: str | None,
    tier: str,            # free|limited|unlimited|concierge
    next_billing_date: str | None,   # ISO 8601, null if free
    home_airport: str | None,        # IATA code, e.g. 'MPM'
    onboarding_complete: bool,
    role: str,            # 'user' | 'admin' | 'agent'
  }
- 401 if no JWT
- 200 otherwise

PYDANTIC SCHEMA
- File: backend/app/schemas/me.py (CREATE THIS FILE)
- Two models: MeOut (response), MePatch (for next card — stub only with all-optional fields)

ROUTER CHANGES
- File: backend/app/routers/profile.py (EXTEND, do not replace)
- If a /me endpoint already exists, just ensure the response shape matches the spec above
- If not, add it
- Import the new schema from app.schemas.me

TEST FILE
- File: backend/tests/test_me_get.py (CREATE)
- Tests:
  1. test_me_requires_auth — no Authorization header → 401
  2. test_me_returns_user — register+login+GET /me returns 200 with all fields
  3. test_me_includes_tier — user.tier='free' → response tier='free', next_billing_date=null
  4. test_me_soft_deleted_user — soft-delete the user, GET /me → 401

Use the existing conftest fixtures (client, user, etc.) — do not create new fixtures.

VERIFICATION
- cd /root/.hermes/workspace/projects/travel-scout.user3/backend
- source .venv/bin/activate (or use uv run)
- pytest tests/test_me_get.py -v
- All 4 tests must pass

DONE WHEN
- All 4 tests pass
- The endpoint returns the documented shape
- Committed: git add -A && git commit -m 'feat(user): GET /api/me'

HARD RULES (each is a fatal mistake)
- DO NOT cat files larger than 50 lines. Use head, tail, grep, search_files.
- DO NOT touch any router other than profile.py
- DO NOT touch models, security, audit, tier_guard, authz, or main.py
- DO NOT install new packages
- DO NOT add a new database column
- If you need to make a change outside the allowed files, BLOCK with a comment explaining what you needed and why
- Time budget: 30 minutes. If you hit 25 minutes, commit what you have and BLOCK with a status comment.

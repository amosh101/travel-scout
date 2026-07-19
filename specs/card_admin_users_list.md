GOAL
admin: GET /api/admin/users — paginated list. ONE endpoint, ONE test file, commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin3
- Branch: wt/t3-admin
- Existing worktree: /root/.hermes/workspace/projects/travel-scout.wt on feat/admin-journey — this is the previous admin worker's worktree with uncommitted changes from the prior failed run. Either commit those first (after reading them) or check them out as a new branch: cd /root/.hermes/workspace/projects/travel-scout && git worktree add -b wt/t3-admin ../travel-scout.admin3 main
- The previous admin worker left uncommitted work in .wt. Read /root/.hermes/workspace/projects/travel-scout.wt with `git status --short` and `git diff --stat` to see what's there. If it's substantial, branch from it. If it's a mess, branch from main.

EXISTING HELPERS
- Existing admin router: backend/app/routers/admin_users.py (may be partial — check)
- require_permission('admin.access'): grep app.services.authz for this
- Search: query string, ilike on email and name
- Tiers: filter on User.tier
- Blocked: filter on User.blocked_at IS NOT NULL

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_users.py (EXTEND), backend/tests/test_admin_users_list.py (CREATE)
- DO NOT modify any user-facing router
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINT
GET /api/admin/users?search=&tier=&blocked=&page=
- Auth: require admin (via require_permission('admin.access'))
- Query params all optional
- Returns: {items: [...], total: int, page: int, per_page: 20}
- Each item: id, email, name, tier, blocked_at (or null), created_at, last_login_at (or null)

ROUTER
- File: backend/app/routers/admin_users.py (EXTEND)
- If a list endpoint already exists, ensure the response shape matches

TEST FILE
- File: backend/tests/test_admin_users_list.py (CREATE)
- 4 tests: search filters (create 2 users, search one), tier filters, blocked filter (block one, set blocked=true), pagination (create 25, page=2 returns 5), non-admin 403

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): GET /api/admin/users list'

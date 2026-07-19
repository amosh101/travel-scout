GOAL
admin: Audit viewer (1 endpoint + CSV export). 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin4
- Branch: wt/t4-admin
- Same worktree

EXISTING HELPERS
- audit_log table: grep 'class Audit' or 'audit_log' in app.models
- Existing admin router: backend/app/routers/admin_audit.py (may have stubs)

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_audit.py (EXTEND), backend/app/schemas/admin_audit.py (CREATE), backend/tests/test_admin_audit.py (CREATE)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 15 minutes

THE ENDPOINT
GET /api/admin/audit?actor=&action=&from=&to=&page=
- Auth: admin
- Query params all optional
- Returns: {items: [{id, actor_id, actor_email, action, target_type, target_id, metadata, created_at}, ...], total, page, per_page: 50}
- Filter: actor (user_id or email), action (exact match or prefix), date range
- If ?format=csv, return Content-Type: text/csv with the same columns

ROUTER
- File: backend/app/routers/admin_audit.py (EXTEND)

SCHEMA
- File: backend/app/schemas/admin_audit.py (CREATE)
- AuditEntryOut

TEST FILE
- File: backend/tests/test_admin_audit.py (CREATE)
- 4 tests: list returns paginated entries, actor filter works, action filter works, CSV export returns 200 with text/csv content type and a header row

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): audit viewer + CSV'

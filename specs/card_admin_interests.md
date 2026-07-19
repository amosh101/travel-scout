GOAL
admin: Interests CRUD (4 endpoints), 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin4
- Branch: wt/t4-admin
- Create the worktree: cd /root/.hermes/workspace/projects/travel-scout && git worktree add -b wt/t4-admin ../travel-scout.admin4 main

EXISTING HELPERS
- Interest model: grep 'class Interest' in app.models
- Soft-delete: use a 'deleted_at' column or 'is_active=False'. If the model doesn't have a soft-delete field, add it via a migration in this card. Document in the commit.

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_interests.py (CREATE), backend/app/schemas/admin_interests.py (CREATE), backend/tests/test_admin_interests.py (CREATE), backend/app/main.py (5 lines max), backend/app/models/__init__.py (only to add deleted_at if missing), backend/migrations/versions/0003_interest_soft_delete.py (CREATE if model was extended)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 20 minutes

THE ENDPOINTS
GET /api/admin/interests
- Auth: admin
- Returns: full catalog with active flag (excludes soft-deleted unless ?include_deleted=true)

POST /api/admin/interests
- Body: {name, slug, category, active: bool = true}
- Creates Interest
- Audit: action='interest_created'

PATCH /api/admin/interests/<id>
- Body: any subset of {name, slug, category, active}
- Audit: action='interest_updated', metadata={changes}

DELETE /api/admin/interests/<id>
- Soft-delete: set deleted_at = now() (or active=False if no deleted_at field)
- Audit: action='interest_deleted'
- Preserves historical user_interests rows (no cascade)

ROUTER
- File: backend/app/routers/admin_interests.py (CREATE)
- Mount in main.py

SCHEMA
- File: backend/app/schemas/admin_interests.py (CREATE)
- InterestOut, InterestCreateIn, InterestUpdateIn

TEST FILE
- File: backend/tests/test_admin_interests.py (CREATE)
- 4 tests: list excludes soft-deleted, create+list round-trip, patch updates active, delete soft-deletes (re-list excludes, but historical user_interests row still exists)

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): interests CRUD'

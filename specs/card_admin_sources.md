GOAL
admin: Data sources manager (5 endpoints) — events + flights. 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin4
- Branch: wt/t4-admin
- Same worktree

EXISTING HELPERS
- Existing admin router: backend/app/routers/admin_sources.py (may have stubs)
- Source models: grep for 'class EventSource' or 'class FlightSource'
- Run-now: spawn a background task (use FastAPI BackgroundTasks or asyncio.create_task). The actual fetch is the existing client code in app/services/data_sources/ or similar.

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_sources.py (EXTEND), backend/app/schemas/admin_sources.py (CREATE), backend/tests/test_admin_sources.py (CREATE)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINTS
GET /api/admin/sources/events
GET /api/admin/sources/flights
- Each returns: {items: [{id, name, api_url, refresh_cron, last_run_at, last_status, failure_count, is_active, last_error}, ...]}

POST /api/admin/sources/<kind>
- kind is 'events' or 'flights'
- Body: {name, api_url, auth_env_var, refresh_cron}
- Creates the source
- Audit: action='source_created'

PATCH /api/admin/sources/<kind>/<id>
- Body: any subset
- Audit: action='source_updated'

POST /api/admin/sources/<kind>/<id>/run
- Triggers immediate fetch via BackgroundTasks
- Returns: {job_id, status: 'started'}
- Updates last_run_at on completion
- Audit: action='source_run_triggered'

ROUTER
- File: backend/app/routers/admin_sources.py (EXTEND)

SCHEMA
- File: backend/app/schemas/admin_sources.py (CREATE)
- SourceOut, SourceCreateIn, SourceUpdateIn, SourceRunOut

TEST FILE
- File: backend/tests/test_admin_sources.py (CREATE)
- 4 tests: list returns registered sources, create adds to list, patch updates is_active, run returns job_id

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): data sources manager'

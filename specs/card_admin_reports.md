GOAL
admin: Reports (5 endpoints). 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin4
- Branch: wt/t4-admin
- Same worktree

EXISTING HELPERS
- All aggregations can use simple SQL COUNT/GROUP BY
- Date range: from/to ISO 8601, applied to User.created_at for signups, to SearchLog for search conversions, to SavedItinerary.saved_at for saved, to Source.last_run_at for source health, to BookingLog.completed_at for agent SLA

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_reports.py (CREATE), backend/app/schemas/admin_reports.py (CREATE), backend/tests/test_admin_reports.py (CREATE), backend/app/main.py (5 lines max)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINTS
GET /api/admin/reports/signups?from=&to=
- Returns: {by_tier: {free: int, limited: int, ...}, by_day: [{date, count}, ...]}

GET /api/admin/reports/conversion?from=&to=
- Returns: {funnel: {visited: int, registered: int, onboarded: int, paid: int}, conversion_rates: {reg_visit: 0.X, paid_onboard: 0.X}}

GET /api/admin/reports/destinations?from=&to=
- Returns: {top_searched: [{destination_id, name, count}, ...], top_saved: [{destination_id, name, count}, ...]}

GET /api/admin/reports/sources?from=&to=
- Returns: {by_source: [{name, last_run_at, failure_count, freshness_score}, ...]}

GET /api/admin/reports/agents?from=&to=
- Returns: {by_agent: [{agent_id, name, completed, sla_hits, sla_misses, sla_hit_rate}, ...]}

ROUTER
- File: backend/app/routers/admin_reports.py (CREATE)
- Mount in main.py

SCHEMA
- File: backend/app/schemas/admin_reports.py (CREATE)
- Each endpoint has its own Out schema (or use a generic ReportOut)

TEST FILE
- File: backend/tests/test_admin_reports.py (CREATE)
- 4 tests: signups returns by_tier + by_day, conversion funnel sums correctly, destinations top-N ordering, sources failure count accurate

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): reports'

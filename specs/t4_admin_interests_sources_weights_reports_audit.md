GOAL
Ship the remaining 5 admin surfaces: interest catalog CRUD, data sources manager, algorithm weights, reports, audit viewer. Foundation has admin_sources.py, admin_weights.py, admin_audit.py as scaffolds. Complete them + add the missing pages.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.wt (worktree feat/admin-journey — same as T3-admin)
- Profile: default

ENDPOINTS

INTERESTS
1. GET /api/admin/interests — full catalog with active flag
2. POST /api/admin/interests — create {name, slug, category, active}
3. PATCH /api/admin/interests/<id> — rename, retag, toggle active
4. DELETE /api/admin/interests/<id> — soft delete (preserves historical user_interests rows)

DATA SOURCES
5. GET /api/admin/sources/events — list with last_run_at, last_status, failure_count
6. GET /api/admin/sources/flights — same
7. POST /api/admin/sources/<kind> — register {name, api_url, auth_env_var, refresh_cron}
8. PATCH /api/admin/sources/<kind>/<id> — edit, toggle is_active
9. POST /api/admin/sources/<kind>/<id>/run — trigger immediate fetch, return job_id, show progress

ALGORITHM WEIGHTS
10. GET /api/admin/weights — current values {interest_overlap, price_weight, date_fit, freshness_decay}
11. PATCH /api/admin/weights — bulk update + audit + store previous value for rollback
12. POST /api/admin/weights/preview — body: {weights, test_user_id} → return top-10 itineraries with these weights applied (read-only computation, no DB write)

REPORTS
13. GET /api/admin/reports/signups?from=&to= — by tier, by day
14. GET /api/admin/reports/conversion?from=&to= — free→paid funnel
15. GET /api/admin/reports/destinations?from=&to= — top searched, top saved
16. GET /api/admin/reports/sources?from=&to= — per-source freshness + failure rate
17. GET /api/admin/reports/agents?from=&to= — SLA hit rate, throughput

AUDIT
18. GET /api/admin/audit?actor=&action=&from=&to= — filterable log
19. CSV export on the audit list

FRONTEND (5 pages)

- /admin/interests (list, create, edit, soft-delete, toggle active)
- /admin/sources (event sources + flight sources, health badges, run-now button, schedule)
- /admin/weights (sliders with debounced save, preview button, rollback to previous)
- /admin/reports (5+ charts using recharts or whatever the project already uses)
- /admin/audit (filterable table, row → drawer with full metadata jsonb)

TESTS

backend/tests/test_admin_interests.py
backend/tests/test_admin_sources.py
backend/tests/test_admin_weights.py
backend/tests/test_admin_reports.py
backend/tests/test_admin_audit.py

- happy paths
- non-admin gets 403
- soft-delete preserves FK references
- weights preview is non-destructive
- audit CSV export works

QUALITY BARS
- [ ] pytest passes
- [ ] All 19 endpoints mounted
- [ ] 5 admin pages render without console errors
- [ ] Every write action writes to audit_log

DONE WHEN
- pytest passes
- All 5 admin surfaces live
- Commit on feat/admin-journey with 'feat(admin): interests + sources + weights + reports + audit'

OUT OF SCOPE
- Anything in T3-admin (already shipping)
- User-facing changes
- Billing
- Booking-agent changes

HARD RULES
- 90 min wall-time
- Reuse the existing admin_*.py files; do not create new admin files
- Reports can use simple aggregates (COUNT/GROUP BY) — don't build a warehouse
- Charts: use the same lib the project already uses for any existing chart

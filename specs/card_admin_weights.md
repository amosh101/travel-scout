GOAL
admin: Algorithm weights (3 endpoints) — get, patch, preview. 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin4
- Branch: wt/t4-admin
- Same worktree

EXISTING HELPERS
- algo_weights table: grep for 'algo_weights' or 'class AlgoWeight' in app.models
- Search/ranking code: app/services/search.py or wherever the intersection runs

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_weights.py (EXTEND), backend/app/schemas/admin_weights.py (CREATE), backend/tests/test_admin_weights.py (CREATE)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 20 minutes

THE ENDPOINTS
GET /api/admin/weights
- Auth: admin
- Returns: {weights: {interest_overlap, price_weight, date_fit, freshness_decay}, updated_at, previous_weights (for rollback)}

PATCH /api/admin/weights
- Body: {interest_overlap?, price_weight?, date_fit?, freshness_decay?}
- Bulk update, store previous for rollback, audit
- Audit: action='weights_updated', metadata={old, new}

POST /api/admin/weights/preview
- Body: {weights: {...}, test_user_id: UUID}
- Applies the new weights to a test user's saved interests/destinations and returns the top 10 itineraries
- Read-only: no DB writes
- Returns: {preview: [{itinerary_id, rank_score, ...}, ...]}

ROUTER
- File: backend/app/routers/admin_weights.py (EXTEND)

SCHEMA
- File: backend/app/schemas/admin_weights.py (CREATE)
- WeightsOut, WeightsPatchIn, WeightsPreviewIn, WeightsPreviewOut

TEST FILE
- File: backend/tests/test_admin_weights.py (CREATE)
- 4 tests: get returns current weights, patch updates and saves previous, preview returns top 10 (use a small fixture), audit log written on patch

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): algorithm weights'

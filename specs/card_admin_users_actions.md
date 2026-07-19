GOAL
admin: POST /api/admin/users/{id}/{block,unblock,impersonate} — 3 endpoints, 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin3
- Branch: wt/t3-admin
- Same worktree

EXISTING HELPERS
- Same as list + invite
- Impersonation: short-lived access token (1h) signed with the same JWT_SECRET_KEY but with a 'role': 'impersonation' claim

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_users.py, backend/tests/test_admin_users_actions.py (CREATE)
- DO NOT modify auth.py or security.py beyond reusing existing helpers
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINTS
POST /api/admin/users/<id>/block
- Sets user.blocked_at = now()
- Cannot block self (compare current_user.id with path id)
- Audit: action='user_blocked', target=id

POST /api/admin/users/<id>/unblock
- Clears user.blocked_at (set to None)
- Audit: action='user_unblocked', target=id

POST /api/admin/users/<id>/impersonate
- Returns: {access_token, expires_at: now+1h, role: 'impersonation'}
- Token is a real JWT with role='impersonation' in claims
- Audit: action='impersonation_started', target=id

ROUTER
- File: backend/app/routers/admin_users.py (EXTEND)

TEST FILE
- File: backend/tests/test_admin_users_actions.py (CREATE)
- 4 tests: block self rejected (admin tries to block own id, 400), block writes audit (create target, block, query audit), unblock clears blocked_at (block, assert blocked_at is set, unblock, assert None), impersonation token has 1h expiry (decode, check exp - now within a few seconds of 3600)

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): user block/unblock/impersonate'

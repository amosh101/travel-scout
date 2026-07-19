GOAL
admin: POST /api/admin/users — create with invite link. ONE endpoint, ONE test file, commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin3
- Branch: wt/t3-admin
- Same worktree as the list card

EXISTING HELPERS
- Same as list
- Invite link: signed JWT, 7-day expiry. Use the existing JWT signing utilities (grep for create_access_token in app.security).
- Single-use: include a jti (JWT ID) in the token. Store used jti values in a new table or extend the User model with a last_invite_jti_used column. ASK FIRST via a comment if you need a new table.

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_users.py, backend/app/schemas/admin_users.py (CREATE), backend/tests/test_admin_users_invite.py (CREATE), backend/app/security.py (only if you need to add a decode helper)
- DO NOT modify any other router
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINT
POST /api/admin/users
- Auth: admin
- Body: {email, name, tier, role}
- Creates user with random temp password (NOT exposed in response — generate via secrets.token_urlsafe)
- Generates invite_url = signed JWT with {user_id, jti, exp: now+7d}
- Returns: {id, email, invite_url, expires_at}
- Audit log: action='user_created', target=user_id, metadata={invited_by, tier}

SCHEMA
- File: backend/app/schemas/admin_users.py (CREATE)
- AdminCreateUserIn, AdminCreateUserOut

TEST FILE
- File: backend/tests/test_admin_users_invite.py (CREATE)
- 4 tests: happy path (POST returns id + invite_url), audit log written, non-admin 403, invalid email 422

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): POST /api/admin/users invite'

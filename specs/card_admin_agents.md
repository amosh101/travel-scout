GOAL
admin: GET /api/admin/agents + suspend/reactivate/capacity. 4 endpoints, 1 test file, 1 commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.admin3
- Branch: wt/t3-admin
- Same worktree

EXISTING HELPERS
- Agent model: grep for 'class Agent' in app.models
- Capacity field: 'max_active' or similar — grep 'max_active'
- Workload: count of SavedItinerary where assigned_agent_id = agent.id AND booking_state IN ('requested', 'in_progress')
- SLA hit rate: from the agent's last 30d of completed bookings, count of those where completion_within_24h = true, divided by total

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: backend/app/routers/admin_agents.py (CREATE), backend/app/schemas/admin_agents.py (CREATE), backend/tests/test_admin_agents.py (CREATE), backend/app/main.py (5 lines max to mount)
- DO NOT modify user-facing routers
- DO NOT install new packages
- Time budget: 25 minutes

THE ENDPOINTS
GET /api/admin/agents
- Auth: admin
- Returns: {items: [{id, email, name, workload, sla_hit_rate, suspended, max_active, created_at}, ...]}

POST /api/admin/agents
- Body: {email, name, max_active}
- Creates user with role='agent'
- Returns: {id, email, invite_url, expires_at} (reuse the invite-link logic from the users invite card)
- Audit: action='agent_created', target=id

POST /api/admin/agents/<id>/suspend
- Sets user.blocked_at (agents use the same blocked_at field as users)
- Audit: action='agent_suspended'

POST /api/admin/agents/<id>/reactivate
- Clears user.blocked_at
- Audit: action='agent_reactivated'

PATCH /api/admin/agents/<id>/capacity
- Body: {max_active: int (>= 1)}
- Updates the agent's max_active
- Audit: action='agent_capacity_changed', metadata={old, new}

ROUTER
- File: backend/app/routers/admin_agents.py (CREATE)
- Mount in main.py

SCHEMA
- File: backend/app/schemas/admin_agents.py (CREATE)
- AgentOut, AgentCreateIn, AgentCapacityIn

TEST FILE
- File: backend/tests/test_admin_agents.py (CREATE)
- 4 tests: list returns agents with workload/sla fields, create returns id+invite, suspend blocks login, capacity update changes max_active

DONE WHEN
- All 4 tests pass
- Committed: 'feat(admin): agents list/create/suspend/capacity'

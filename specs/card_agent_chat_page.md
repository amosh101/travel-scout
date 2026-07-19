GOAL
frontend /agent-chat — concierge message thread. ONE page, commit.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.user4
- Branch: wt/t4-user
- Same worktree as /profile

EXISTING HELPERS
- Theme: same as /profile (use the same color tokens, layout primitives)
- Polling: setInterval 3000ms, clear on unmount
- For tier check: fetch /api/profile/me on load; if tier != 'concierge', redirect to /itineraries

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: frontend/app/agent-chat/page.tsx (CREATE), frontend/lib/agent-chat.ts (CREATE only if needed for shared logic)
- DO NOT modify any other page
- DO NOT install new packages
- Time budget: 30 minutes

THE PAGE
- frontend/app/agent-chat/page.tsx
- On load: GET /api/profile/me. If tier != 'concierge' → redirect to /itineraries (use Next.js router)
- Layout: two-column. Left sidebar (1/3 width): list of user's itineraries. Right pane (2/3): thread view.
- Sidebar: fetch from /api/profile/itineraries (or whatever endpoint returns the user's itineraries — check existing /saved page). For each: show event title + dates. Click selects it.
- Thread view:
  - GET /api/messages?itinerary_id=<selected> on select
  - Render messages in chronological order, each showing sender_role + body + created_at
  - Polling: setInterval(3000ms). On each tick, GET /api/messages?itinerary_id=<selected>&since=<lastSeen>. Append new messages.
  - Post box at the bottom: textarea + Send button. POST /api/messages on send. Clear the textarea.
  - On post error: show toast.
- Empty state: "No messages yet. Start the conversation."
- Loading state: spinner (use the same spinner pattern as /saved or /itineraries)
- On unmount: clearInterval

THEME
- Same as /profile
- Two-column on desktop, stacked on mobile

TESTS
- Skip if no test runner. Manual verification only.

DONE WHEN
- Page renders for concierge users
- Page redirects for free/limited/unlimited users
- Posting a message works
- Polling updates the thread (post in another tab/window, see it appear)
- Committed: 'feat(user): /agent-chat page'

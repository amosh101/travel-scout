GOAL
frontend /saved — add agent CTA + outbound link. EXTEND the existing page; do not rewrite.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.user4
- Branch: wt/t4-user
- Same worktree

EXISTING HELPERS
- /saved page already exists; READ IT FIRST to understand its current shape
- The page should already be fetching /api/profile/itineraries/saved or similar — check

HARD RULES
- DO NOT cat files larger than 50 lines (read /saved with head/tail)
- Allowed files: frontend/app/saved/page.tsx (EXTEND only, do not rewrite), frontend/lib/saved.ts (CREATE only if needed)
- DO NOT install new packages
- Time budget: 20 minutes

THE CHANGES
- File: frontend/app/saved/page.tsx
- For each saved itinerary card:
  - If user.tier == 'concierge' AND booking_state in ['requested', 'saved']: render a "Message my agent" button → navigate to /agent-chat?itinerary=<id> (use Next.js router)
  - If itinerary has outbound_url: render an "Open booking link" button (anchor with target=_blank rel=noopener) for free+ tiers (everyone, since outbound link is part of the limited tier)
- Keep all existing functionality intact: list, sort, filter, pagination, etc.
- Style: match the existing button styles on the page

DONE WHEN
- "Message my agent" appears for concierge users with requested/saved itineraries
- "Open booking link" appears when outbound_url is set
- Existing list behaviour unchanged
- Committed: 'feat(user): /saved agent CTA + outbound link'

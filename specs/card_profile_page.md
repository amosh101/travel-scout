GOAL
frontend /profile — real edit page. ONE page, commit. No exploration.

WORKSPACE
- /root/.hermes/workspace/projects/travel-scout.user4
- Branch: wt/t4-user

EXISTING HELPERS
- Theme: black-responsive, matches /onboarding. Read /onboarding page ONCE for the styling pattern.
- API client: frontend/lib/api.ts (read ONCE for the auth header pattern)
- Form: native React (useState, useEffect) — do not introduce a new form library

HARD RULES
- DO NOT cat files larger than 50 lines
- Allowed files: frontend/app/profile/page.tsx (CREATE), frontend/app/profile/layout.tsx (CREATE if needed), frontend/lib/ (only if you need ONE new helper)
- DO NOT modify any other page
- DO NOT install new packages
- Time budget: 30 minutes

THE PAGE
- frontend/app/profile/page.tsx
- On load: GET /api/profile/me (note: the endpoint is /api/profile/me due to router prefix; see backend pilot)
- Editable form: name, nationality, passport, dob (date input), emergency_contact_name, emergency_contact_phone, home_airport (IATA code, 3 letters)
- "Change password" inline section (expandable): old_password, new_password (min 8) → POST /api/profile/me/change-password
- "Export my data" button → GET /api/profile/me/export → trigger JSON download via window.URL.createObjectURL
- "Delete my account" button (double-confirm: first click reveals "Are you sure?" + "Yes, delete" + "Cancel") → DELETE /api/profile/me
- Tier badge in the header (use the tier from /me response)
- "Manage billing" link to /billing (out of scope but the link should exist)
- On save: PATCH /api/profile/me, show toast (use the existing toast pattern from /onboarding or /register)
- On error: show toast with the server's error message

THEME
- Black background, white text, accent color matches /onboarding
- Mobile-responsive (match /onboarding breakpoints)
- max-w-2xl container

TESTS
- Skip frontend unit tests if the project doesn't have a test runner set up
- Manual verification: page loads, form saves, export downloads, delete blocks

DONE WHEN
- Page renders without console errors
- Form saves and shows success toast
- Export downloads a JSON file
- Delete shows double-confirm and blocks
- Committed: 'feat(user): /profile page'

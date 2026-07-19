# Travel-Scout — Product Requirements Document (PRD)

**Author:** Alfred
**Date:** 10 July 2026
**Status:** SIGNED OFF — product definition locked

---

## 1. The product (one paragraph)

Travel-scout plans trips that match the user's **interests** by finding the real-world **intersection** of (a) dates, (b) destination, (c) anchor events the user is attending, and (d) other events / holidays / public gatherings happening at that destination during that window. The intersection algorithm is the product; the UI is how the user steers it.

## 2. Target user (locked)

- **Now:** Sir (Maputo). Single user, multi-tenant data model already in place.
- **Future:** Sold as a product. The architecture must not require a refactor when the second user signs up.
- The product is built for **me first, sold second**. No design choices for the second user that sacrifice the first user's experience.

## 3. The user journey (locked)

1. User states **interests** (e.g. F1, Belgian National Day, jazz, cycling, Italian Renaissance).
2. User states **dates** and a **destination** (or lets the system suggest).
3. Until the user specifies the events they want to attend, **all relevant events are anchors** — the system surfaces everything that matches interests at that destination during that window.
4. Once the user picks the events they will attend, the system **suggests other relevant events** in the same window that match the same interests (so the trip is fuller, not just the one anchor).
5. The final itinerary is a single artifact: destination, dates, anchor events + suggested events, logistics.

## 4. Data rules (locked)

- All flight, event, and price data is **real and current**. Sources are refreshed on a schedule.
- **No paid APIs in v1.** Only free, open sources: Jolpica (F1), Nager.Date (public holidays), Nominatim/OSRM/Overpass (OpenStreetMap), Wikipedia, Open Trivia, public RSS.
- The system **never claims to know something it does not know.** If a source is down or returns empty, the surface area says so. No "sample data," no fabricated events, no placeholder prices.
- A fresh source that comes online later is added without code refactor (config + one fetcher file).

## 5. Front-end rules (locked)

- The front-end must work as specified because **that is how users interact with the product.** No CLI-only / Telegram-only build paths. The Next.js front-end is a first-class surface.
- Every user-facing feature is built end-to-end (API + UI) or not built.
- The front-end is mobile-first (Sir uses iPhone; future users will too).

## 6. The 7-lens (Sir's standing order)

Every request runs through all seven lenses before action:
1. **Personal assistant** — what does Sir actually need?
2. **10x SWE** — what's the right architecture, not the convenient one?
3. **Fortune 500 chief of staff** — consolidate the noise, don't add to it
4. **Founder/CEO** — what's the most leveraged thing right now?
5. **Ops manager** — what would break? what's the steady-state?
6. **Finance planner** — what does this cost in $ and time?
7. **Local law partner (MZ+EU+US)** — any flags? PCI, GDPR, Mozambique cyber-crime, export controls?

## 7. The data sources (committed)

**Free, no key, in production:**
- Jolpica F1 (`api.jolpi.ca`) — 2026 calendar, all 22 races
- Nager.Date (`date.nager.at`) — public holidays, 15 SADC countries + Belgium
- OpenStreetMap Nominatim — geocoding (1.1s rate limit per ToS)
- OSRM — routing (public demo server, ~2 req/sec)
- OpenStreetMap Overpass — POI / hotel lookup (unreliable, 3-mirror fallback)

**Gated behind keys (raise NotConfiguredError if called):**
- Kiwi Tequila (flights) — needs `KIWI_API_KEY`
- Ticketmaster Discovery (events) — needs `TICKETMASTER_API_KEY`
- Stripe (payments) — test mode ready, live mode needs full Stripe Connect

## 8. The non-goals

- We will NOT use fake/sample data anywhere
- We will NOT add features Sir hasn't asked for
- We will NOT claim to do something the underlying API doesn't actually support
- We will NOT take external actions (email, post, trade, book) without explicit "go"
- We will NOT store payment details ourselves
- We will NOT scrape websites that prohibit scraping

## 9. The hard rules (from user profile)

- 2026-06-30: No mock data. Real data or nothing.
- 2026-07-01: Don't ask permission for simple stuff. Just execute.
- 2026-07-09: Placeholders are mock data. The only honest placeholder is an empty state with "no data yet" label. Sequence real-first, decoration-last.
- 2026-07-09: Read the disk first. The schema is the spec. Don't propose a redesign before reading the schema.
- 2026-07-10: Ask fewer questions. Make defensible inferences. Build. Don't second-guess.

## 10. The technical scope (T1–T6)

| Card | Status | Real data sources |
|---|---|---|
| T1 — infra (postgres, redis, api, web) | ✅ live | docker compose |
| T2 — UI shell | ✅ live (no fake data, search form wired) | OSM theme |
| T3 — auth + search | ✅ live for free APIs | Jolpica, Nominatim, OSRM, Nager.Date, /api/search, /api/discover |
| T4 — itineraries | ❌ not started | needs auth + saved searches |
| T5 — admin | ❌ not started | user management, source config |
| T6 — agent (chat interface) | ❌ not started | wraps the rest |

## 11. The infrastructure reality (Tailscale-bound)

**Live on Tailscale (100.91.143.50):**
- :3000 — Travel-Scout web (Next.js 14.2.20, public over Tailscale)
- :8000 — Travel-Scout API (FastAPI, public over Tailscale)
- :8888 — Dashboard (Python http.server, public over Tailscale, no auth)

**Not on Tailscale:**
- Stripe, Kiwi, Ticketmaster — need keys
- :8090 — was document server, recycled, files archived to `/root/.hermes/archive/cc_host_spec_2026-07-10/`

---

*This document is the source of truth. Future work cites this PRD. No revision without explicit Sir override.*

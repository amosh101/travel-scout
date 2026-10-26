# Data sources

Registry of the free and key-gated data sources behind the event pipeline.
Statuses verified against live code and containers on 2026-10-26.

## Free sources — live, no signup needed

| Source           | Auth | Used for                                            | Status |
|------------------|------|-----------------------------------------------------|--------|
| Wikidata SPARQL  | none | interest events by country (season anchors)          | live, on-request |
| Wikipedia API    | none | "List of" scrapes + city-article infobox search      | live, on-request |
| Jolpica-F1       | none (optional key) | F1 season races → trip anchors               | live (2026 season) |
| Nager.Date       | none | public holidays per country                          | live |
| Nominatim        | none | geocoding fallback in location resolver              | live |
| Overpass (OSM)   | none | POI lookups (3 mirrors, failover)                    | live |
| OSRM demo server | none | routing/distance                                     | live, shared rate limits |
| Interest feeds   | none | 15 RSS feeds (BBC, Guardian x9, Autosport, The Race, Pitchfork, DJ Mag, Designboom, Eater, Reddit r/formula1, Club of Mozambique, NewsDay ZW, Daily Maverick) | live |
| GeoNames         | free `GEONAMES_USERNAME` | 4th leg of location resolver | wired, awaiting key |

Keyless clients read no env vars. The resolver only skips GeoNames when
`GEONAMES_USERNAME` is empty — polite skip, never fake data.

## Key-gated sources — wired, silent until the key lands

| Source                 | Env var                | Free tier                 | Status |
|------------------------|------------------------|---------------------------|--------|
| Ticketmaster Discovery | `TICKETMASTER_API_KEY` | 5,000 calls/day, ~5 req/s | client done; inactive until key set |
| Kiwi.com Tequila       | `KIWI_API_KEY`         | **closed to new users** (invite-only since May 2024) | client kept; will stay not-configured |

Tequila is not obtainable by self-service signup. If flight pricing is
wanted later, the realistic path is Amadeus Self-Service (free test tier)
— quota to be probed before any client is written.

## Ingest into the scrape ledger

The discover pipeline scrapes on request and keeps results in process
(1h feeds / 24h free-events TTL). It does **not** write the ledger.
`scraped_events` / `scraped_locations` / `scraped_runs` are populated by
two scheduled no-agent jobs (deliver local, receipts in `scraped_runs`):

  - Catalog sweep — daily 06:20 UTC+2 (04:20 UTC), cron `b183f36946f7`,
    script `~/.hermes/scripts/travel_scout_catalog.sh` →
    `backend/app/scripts/catalog_event_sweep.py` (reads the live
    destinations table; least-recently-swept city ordering).
  - Marquee sites — daily 06:45 UTC+2 (04:45 UTC), cron `b31d8e9cdadb`.

Manual backfill equivalent (not normally needed):

    docker cp .audits/ingest_free_events.py <api>:/tmp/
    docker exec -w /app -e PYTHONPATH=/app <api> python /tmp/ingest_free_events.py

## Notes

- `events` / `event_sources` are the v2 managed-catalog stubs; `events` is
  empty. The scrape ledger is the raw store.
- Ledger rows scraped 2026-07-20 predate the v2 rewrite and are
  city-less/dateless backfill output; consider a one-time cleanup.
- The weekly digest scheduler (`digests` table) builds destination cards
  from the live pipeline; it has its own per-user payloads.
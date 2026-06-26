# Data sources

| Source         | Auth         | Free tier | Used for                          | Status          |
|----------------|--------------|-----------|------------------------------------|-----------------|
| Ticketmaster Discovery | API key | 5K calls/day, 5 req/sec | Music, sports, arts events | stub interface ready |
| Jolpica F1     | public       | unlimited | Formula 1 schedule (2026/2027)    | stub interface ready |
| Kiwi.com Tequila | API key | 1K calls/month on free | Flights                | stub interface ready |

Auth keys are read from `KIWI_API_KEY`, `TICKETMASTER_API_KEY`,
`JOLPICA_API_KEY` env vars via the `app.clients.*` factories. Empty/missing =
client returns `NotConfiguredError`; never fake data.

## Why these three

- **Ticketmaster** — best coverage of music + sports + arts at free-tier
  volume. Recommended in v1's `EVENT_DATA_SOURCES.md` research note.
- **Jolpica** — Ergast-compatible F1 schedule (free, public). Sir is an F1
  fan; covered from MVP.
- **Kiwi.com** — best flight pricing API on free tier; was the primary flight
  source in v1.
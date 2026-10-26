-- Pass 3 official-site persistence: Geneva / Amsterdam / Madrid / Milan
-- Sources verified by hand 2026-10-26 (see raw.source_url per row).

-- keep location rows fresh (same keys as passes 1-2)
INSERT INTO scraped_locations (id, source, source_id, name, country_alpha2, scraped_at, expires_at)
VALUES (gen_random_uuid(), 'location_resolver', 'CH:Geneva', 'Geneva', 'CH', now(), now() + interval '30 days'),
       (gen_random_uuid(), 'location_resolver', 'NL:Amsterdam', 'Amsterdam', 'NL', now(), now() + interval '30 days'),
       (gen_random_uuid(), 'location_resolver', 'ES:Madrid', 'Madrid', 'ES', now(), now() + interval '30 days'),
       (gen_random_uuid(), 'location_resolver', 'IT:Milan', 'Milan', 'IT', now(), now() + interval '30 days')
ON CONFLICT (source, source_id) DO UPDATE
  SET scraped_at = EXCLUDED.scraped_at, expires_at = EXCLUDED.expires_at;

WITH loc AS (
  SELECT name, id FROM scraped_locations WHERE source='location_resolver'
    AND source_id IN ('CH:Geneva','NL:Amsterdam','ES:Madrid','IT:Milan')
)
INSERT INTO scraped_events
  (id, source, source_id, name, kind, interest_key, starts_at, ends_at,
   location_id, wikidata_qid, raw, scraped_at, expires_at, dedupe_year)
SELECT gen_random_uuid(), v.source, v.source_id, v.name, v.kind, v.interest_key,
       v.starts::date,
       CASE WHEN v.ends IS NULL THEN NULL ELSE v.ends::date END,
       loc.id, v.qid, v.raw::jsonb, now(), now() + interval '30 days',
       date_part('year', v.starts::date)::int
FROM (VALUES
  ('official-site', 'giff-2026|Geneva|2026-10-30',
   'Geneva International Film Festival (GIFF 2026)', 'film_festival', 'film',
   '2026-10-30', '2026-11-08', 'Geneva', 'Q5121157',
   '{"source_url": "https://2026.giff.ch/", "city": "Geneva", "country": "CH",
     "sweep": "pass3-official",
     "date_note": "official site: Le GIFF du 30 octobre au 8 novembre 2026"}'),
  ('official-site', 'escalade-race|Geneva|2026-12-05',
   'Course de l''Escalade (48e edition)', 'running_race', 'marathon',
   '2026-12-05', '2026-12-06', 'Geneva', 'Q1137736',
   '{"source_url": "https://www.escalade.ch/", "city": "Geneva", "country": "CH",
     "sweep": "pass3-official",
     "date_note": "official site: rendez-vous les 5 et 6 decembre 2026, 48e edition"}'),
  ('official-site', 'amsterdam-light-festival-15|Amsterdam|2026-11-26',
   'Amsterdam Light Festival - Edition 15', 'light_art_festival', 'design',
   '2026-11-26', '2027-01-17', 'Amsterdam', 'Q26156861',
   '{"source_url": "https://amsterdamlightfestival.com/", "city": "Amsterdam",
     "country": "NL", "sweep": "pass3-official",
     "date_note": "official site: 26.11.2026 - 17.01.2027"}'),
  ('official-site', 'jazzmadrid26|Madrid|2026-10-02',
   'JAZZMADRID26 - Festival Internacional de Jazz de Madrid', 'music_festival',
   'jazz', '2026-10-02', '2026-11-30', 'Madrid', NULL,
   '{"source_url": "https://www.esmadrid.com/agenda/jazzmadrid-festival-internacional-de-jazz-de-madrid",
     "city": "Madrid", "country": "ES", "sweep": "pass3-official",
     "date_note": "official city portal: del 2 de octubre al 30 de noviembre de 2026; ongoing as of 2026-10-26"}'),
  ('wikipedia', 'oh-bej-oh-bej|Milan|2026-12-07',
   'Oh bej! Oh bej! (Christmas fair)', 'christmas_fair', 'food-wine',
   '2026-12-07', '2026-12-13', 'Milan', NULL,
   '{"source_url": "https://en.wikipedia.org/wiki/Oh_bej!_Oh_bej!",
     "city": "Milan", "country": "IT", "sweep": "pass3-official",
     "date_note": "article rule: held from 7 December (St Ambrose Day) until the following Sunday; 2026 window derived (Mon 7 -> Sun 13 Dec)"}')
) AS v(source, source_id, name, kind, interest_key, starts, ends, city, qid, raw)
JOIN loc ON loc.name = v.city
ON CONFLICT (source, source_id, dedupe_year) DO UPDATE
  SET name = EXCLUDED.name, kind = EXCLUDED.kind,
      starts_at = EXCLUDED.starts_at, ends_at = EXCLUDED.ends_at,
      location_id = EXCLUDED.location_id, raw = EXCLUDED.raw,
      scraped_at = EXCLUDED.scraped_at, expires_at = EXCLUDED.expires_at;

-- receipts
INSERT INTO scraped_runs
  (id, source, scraper, started_at, finished_at, status, added, updated, error, duration_ms)
VALUES
  (gen_random_uuid(), 'official-site', 'CityEventSweep3-official', now(), now(), 'success', 4, 0, NULL, 0),
  (gen_random_uuid(), 'wikipedia', 'CityEventSweep3-official', now(), now(), 'success', 1, 0, NULL, 0);
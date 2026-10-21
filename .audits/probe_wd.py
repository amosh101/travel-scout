"""Probe the Wikidata jazz query path: what SPARQL runs, what returns."""
import asyncio, json
from datetime import date
import requests as _rq  # repo uses curl_cffi alias? check import name inside module
from app.clients import free_events as fe

agg = fe.build_free_event_aggregator()
wd = agg.wikidata

# Rebuild the jazz query via the client's own builder
types = fe._EVENT_TYPE_QIDS.get("jazz", [])
genres = fe._GENRE_FILTER_QIDS.get("jazz", [])
try:
    sparql = wd._build_query(
        event_types=types, genre_filters=genres, country_qid=None,
        start_iso="2026-10-21", end_iso="2027-04-19", limit=25,
    )
    print("=== SPARQL ===")
    print(sparql[:1200])
except Exception as e:
    print("build_query failed:", type(e).__name__, e)

recs = asyncio.run(wd.search(
    interest_key="jazz",
    country_alpha2=None,
    start_date=date(2026, 10, 21),
    end_date=date(2027, 4, 19),
    limit=25,
))
print("records:", len(recs))
for r in recs[:6]:
    print("  ", r.name[:44], "|", r.starts_at, "|", r.city[:24] if r.city else "-", "|", r.kind)
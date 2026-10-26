import logging
from datetime import date

from app.scripts.catalog_event_sweep import (
    city_qid_batch, wikivoyage_events_wikitext, parse_recurring_rules,
    run_sparql, parse_sparql_rows,
)

logging.basicConfig(level=logging.INFO)

today, horizon = date(2026, 10, 26), date(2027, 3, 25)
qids = city_qid_batch([("Vienna", "AT"), ("Cape Town", "ZA"),
                       ("Tokyo", "JP")])
print("QIDS:", qids)

wts = wikivoyage_events_wikitext("Tokyo")
rules = parse_recurring_rules("\n".join(wts), today, horizon)
print("WIKIVOYAGE rules (tokyo):", rules[:4])

try:
    v = qids.get("Vienna|AT")
    rows = parse_sparql_rows(run_sparql(v, today, horizon, 15, deep=False))
    print("SPARQL vienna simple rows:", len(rows), rows[:2])
except Exception as e:
    print("SPARQL smoke error:", type(e).__name__)
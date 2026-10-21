import re, sys
from datetime import date
sys.path.insert(0, "/app")
from app.clients.interest_feeds import _DATE_PATTERNS, _MONTHS

cases = [
    "Cape Town Jazz Festival runs 25 March 2027 on the Greenmarket Square",
    "Grand Prix weekend: 2026-11-15 in Las Vegas",
    "Nov 12, 2027: one-night-only show",
    "tickets on sale next week",
    "12 November 2027 gala dinner",
]
for c in cases:
    m = None
    which = -1
    for i, pat in enumerate(_DATE_PATTERNS):
        m = pat.search(c)
        if m:
            which = i
            break
    if m:
        print(f"case '{c[:45]}' -> pattern#{which} groups={m.groups()}")
    else:
        print(f"case '{c[:45]}' -> no match")
# now exec the real function on each with traceback isolation
from app.clients.interest_feeds import _parse_event_date
for c in cases:
    try:
        print(_parse_event_date(c), "<-", c[:50])
    except Exception as e:
        print("CRASH:", type(e).__name__, e, "<-", c[:50])
        mm = None
        for i, pat in enumerate(_DATE_PATTERNS):
            mm = pat.search(c)
            if mm:
                break
        if mm:
            g = [s.lower() if isinstance(s, str) else int(s) for s in mm.groups()]
            print("   g:", g)
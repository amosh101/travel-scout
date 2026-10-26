#!/usr/bin/env python3
"""Pass 3c v2: fast Wikidata SPARQL probe.

Leg A: editions of the 4 undated series (P361/P179/P527) with dates.
Leg B: EntitySearch (mwapi) per curated term - the same lookup
       wbsearchentities performs, but issued inside SPARQL so we
       avoid the rate-limited api.php pool.

Dates are real claims (P580/P585, optional P582). Prints JSON; the
host-side follow-up persists what falls inside the window.
"""

import json
import re
import urllib.parse
import urllib.request

UA = "travel-scout-city-sweep/3.3 (github.com/amosh101/travel-scout)"
URL = "https://query.wikidata.org/sparql"

SERIES = ["Q26156861", "Q1137736", "Q5121157", "Q125737552"]
TERMS = [
    "Jazz Madrid", "Madrid Christmas market", "San Silvestre Vallecana",
    "Oh Bej", "Milan Christmas market", "Milano Film Festival",
    "Amsterdam Light Festival", "Amsterdam Christmas market",
    "Geneva Christmas market", "Escalade Geneva",
    "Geneva Film Festival 2026", "Milano Marathon",
]
WINDOW_START, WINDOW_END = "2026-10-26", "2027-03-25"


def build_query():
    vals = " ".join(f"wd:{q}" for q in SERIES)
    legs = [f"""
  VALUES ?series {{ {vals} }}
  {{ ?item (wdt:P361|wdt:P179) ?series . BIND('A-edition' AS ?leg) }}
  UNION
  {{ ?series wdt:P527 ?item . BIND('A-hasPart' AS ?leg) }}"""]
    for t in TERMS:
        tl = json.dumps(t)
        legs.append(f"""
  Service wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org" ;
                    wikibase:api "EntitySearch" ;
                    mwapi:search {tl} ;
                    mwapi:language "en" .
    ?item wikibase:apiOutputItem mwapi:item .
  }}
  BIND('T-{t}' AS ?leg)""")
    union = "\n  UNION\n  ".join("{\n" + leg + "\n  }" for leg in legs)
    return f"""
SELECT ?item ?itemLabel ?leg ?start ?end WHERE {{
  {union}
  ?item wdt:P31 ?cls .
  OPTIONAL {{ ?item wdt:P580 ?s0 }}
  OPTIONAL {{ ?item wdt:P585 ?s1 }}
  OPTIONAL {{ ?item wdt:P582 ?end }}
  BIND(COALESCE(?s0, ?s1) AS ?start)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 400"""


def run(q):
    data = urllib.parse.urlencode({"query": q, "format": "json"}).encode()
    req = urllib.request.Request(URL, data=data, headers={
        "User-Agent": UA, "Accept": "application/sparql-results+json"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read())


try:
    payload = run(build_query())
    bindings = payload.get("results", {}).get("bindings", [])
    out, seen = [], set()
    for b in bindings:
        try:
            qid = re.search(r"(Q\d+)$", b["item"]["value"]).group(1)
            start = b.get("start", {}).get("value", "")[:10]
            end = b["end"]["value"][:10] if b.get("end") else None
            leg = b.get("leg", {}).get("value", "")
            key = (qid, start or "")
            if key in seen:
                continue
            seen.add(key)
            out.append({"qid": qid,
                        "name": b.get("itemLabel", {}).get("value", qid),
                        "leg": leg, "start": start, "end": end,
                        "url": f"https://www.wikidata.org/wiki/{qid}"})
        except (KeyError, AttributeError, ValueError):
            continue
    in_window = [row for row in out
                 if WINDOW_START <= row["start"] <= WINDOW_END]
    print(json.dumps({"matched": len(out), "in_window": len(in_window),
                      "rows": out}, indent=2))
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
import json, re
from curl_cffi import requests as cffi_requests

UA = "travel-scout-catalog-sweep/1.0 (github.com/amosh101/travel-scout)"
URL = "https://query.wikidata.org/sparql"
vals = '"Cape Town"@en "Tokyo"@en "Vienna"@en'
qa = (
    "SELECT ?item ?lbl WHERE {\n"
    f"  VALUES ?lbl {{ {vals} }}\n"
    "  ?item rdfs:label ?lbl .\n"
    "  { ?item wdt:P31/wdt:P279* wd:Q515 . }\n"
    "  UNION\n"
    "  { ?item wdt:P31 wd:Q5119 . }\n"
    "} LIMIT 300")
r = cffi_requests.get(URL, params={"query": qa, "format": "json"},
                      headers={"User-Agent": UA,
                               "Accept": "application/sparql-results+json"},
                      impersonate="chrome120", timeout=60)
print("phaseA status:", r.status_code)
cand = {}
for b in r.json().get("results", {}).get("bindings", []):
    lbl = b["lbl"]["value"]
    qid = b["item"]["value"].rsplit("/", 1)[-1]
    cand.setdefault(lbl, set()).add(qid)
print("candidates:", {k: sorted(v) for k, v in cand.items()
                      if k in ("Cape Town", "Tokyo", "Vienna")})

items = " ".join("wd:" + q for qs in cand.values() for q in sorted(qs))
qb = (
    "SELECT ?item ?iso2 WHERE {\n"
    f"  VALUES ?item {{ {items} }}\n"
    "  ?item wdt:P17 ?c .\n"
    "  ?c wdt:P300 ?iso2 .\n"
    "} LIMIT 500")
r2 = cffi_requests.get(URL, params={"query": qb, "format": "json"},
                       headers={"User-Agent": UA,
                                "Accept": "application/sparql-results+json"},
                       impersonate="chrome120", timeout=60)
print("phaseB status:", r2.status_code)
iso = {}
for b in r2.json().get("results", {}).get("bindings", []):
    qid = b["item"]["value"].rsplit("/", 1)[-1]
    iso[qid] = b["iso2"]["value"]
for lbl in ("Cape Town", "Tokyo", "Vienna"):
    qs = sorted(cand.get(lbl, set()))
    print(lbl, [(q, iso.get(q)) for q in qs])
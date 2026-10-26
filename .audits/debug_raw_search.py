import json
from curl_cffi import requests

UA = "travel-scout-catalog-sweep/1.0 (github.com/amosh101/travel-scout)"

for q in ("food and wine festival Amsterdam", "marathon Amsterdam",
          "music festival Amsterdam"):
    r = requests.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query", "list": "search", "srsearch": q,
        "srlimit": "6", "format": "json"},
        headers={"User-Agent": UA}, impersonate="chrome120", timeout=15)
    hits = r.json().get("query", {}).get("search", [])
    print(q, "=> status", r.status_code, "hits", len(hits),
          [h["title"][:40] for h in hits[:3]])
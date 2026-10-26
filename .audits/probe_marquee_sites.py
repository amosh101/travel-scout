#!/usr/bin/env python3
"""Probe candidate official event pages for 2026/27 date windows.

Prints per-URL: HTTP status, matched date-window lines (with context),
and a normalised window candidate. The humans (Alfred + Sir) vet these
before any registry entry gets wired.
"""

import json
import re

from curl_cffi import requests

UA = "travel-scout-marquee-probe/1.0 (github.com/amosh101/travel-scout)"

SITES = {
    "dubai_marathon": "https://www.dubaimarathon.org/",
    "dsf_dubai": "https://www.visitdubai.com/en/articles/dsf-events",
    "singapore_marathon": "https://www.singaporemarathon.com/",
    "tokyo_marathon": "https://marathon.tokyo/en/",
    "thailand_marathon_bkk": "https://amazingthailandmarathon.com/",
    "hk_marathon": "https://www.hkmarathon.com/",
    "hk_sevens": "https://www.hk7s.com/",
    "hk_arts_festival": "https://www.hk.artsfestival.org/en/",
    "shanghai_marathon": "http://www.sh-marathon.com/",
    "seoul_marathon": "https://seoulmarathon.co.kr/eng/index.asp",
    "athens_marathon": "https://www.athensauthenticmarathon.gr/site/home/",
    "marrakech_marathon": "https://marathonmarrakech.com/",
    "cape_town_cycle_tour": "https://www.capetowncycletour.com/",
    "cape_town_jazz": "https://www.capetownjazzfest.com/",
    "vienna_christkindlmarkt": "https://www.christkindlmarkt.co.at/en/",
    "jazzfest_berlin": "https://www.berlinerfestspiele.de/en/berliner-festspiele/programm/jazzfest-berlin",
    "cairo_ciff": "https://ciff.org.eg/",
    "budapest_advent": "https://adventbudapest.hu/en/",
    "prague_christmas": "https://www.prazskevanoce.cz/en",
    "cph_light_festival": "https://copenhagenlightfestival.org/",
    "web_summit": "https://websummit.com/",
    "azgo_maputo": "https://azgofestival.com/",
}

MONTHS = ("january|february|march|april|may|june|july|august|september|"
          "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|"
          "nov|dec")
# loose date-window patterns: "4-6 December 2026", "Dec 4-6, 2026",
# "04.12.-06.12.2026", "December 4, 2026"
PATTERNS = [
    rf"(\d{{1,2}}(?:\s*(?:[&\-–—]|to|bis)\s*\d{{1,2}})?\s+(?:{MONTHS})\s+20\d\d)",
    rf"((?:{MONTHS})\s+\d{{1,2}}(?:\s*(?:[&\-–—]|to)\s*\d{{1,2}})?,?\s+20\d\d)",
    r"(\d{1,2}\.\d{1,2}\.(?:-|\s*bis\s*)?\d{1,2}\.\d{1,2}\.20\d\d)",
    r"(\d{1,2}\s*[-–—]\s*\d{1,2}\s+(?:{MONTHS})\s+20\d\d)".replace(
        "{MONTHS}", MONTHS),
]
RX = re.compile("|".join(PATTERNS), re.I)

for key, url in SITES.items():
    try:
        r = requests.get(url, headers={"User-Agent": UA},
                         impersonate="chrome120", timeout=25)
        status = r.status_code
        text = re.sub(r"\s+", " ", r.text)
        title_m = re.search(r"<title[^>]*>([^<]{0,120})",
                            r.text, re.I)
        title = title_m.group(1).strip() if title_m else ""
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"key": key, "url": url,
                          "error": f"{type(exc).__name__}: {exc}"}))
        continue
    matches, seen = [], set()
    for m in RX.finditer(text):
        s = max(0, m.start() - 60)
        ctx = text[s:m.end() + 60]
        norm = m.group(1)
        if norm in seen:
            continue
        seen.add(norm)
        matches.append({"date": norm, "context": ctx[:180]})
        if len(matches) >= 4:
            break
    print(json.dumps({"key": key, "url": url, "status": status,
                      "title": title, "dates": matches}))
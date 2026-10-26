#!/usr/bin/env python3
"""Probe round 2: corrected/alternative official URLs."""
import json
import re
from curl_cffi import requests

UA = "travel-scout-marquee-probe/1.1 (github.com/amosh101/travel-scout)"
SITES = {
    "athens_marathon": "https://www.athensmarathon.com/",
    "jazzfest_berlin": "https://jazzfest-berlin.de/en/",
    "ciff_cairo_programme": "https://ciff.org.eg/en/dates/",
    "christkindlmarkt_vienna": "https://www.christkindlmarkt.at/en",
    "cph_light": "https://copenhagenlightfestival.org/program/",
    "marrakech_marathon_2": "https://marathonmarrakech.com/en/home/",
    "hk_af_dates": "https://www.hk.artsfestival.org/en/about/",
    "hk_marathon_info": "https://www.hkmarathon.com/event-info/",
}
MONTHS = ("january|february|march|april|may|june|july|august|september|"
          "october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec")
PAT = (rf"(\d{{1,2}}(?:\s*(?:[&\-–—]|to|bis|and)\s*\d{{1,2}})?\s+(?:{MONTHS})\s+20\d\d"
       rf"|(?:{MONTHS})\s+\d{{1,2}}(?:\s*(?:[&\-–—]|to|and)\s*\d{{1,2}})?,?\s*20\d\d"
       r"|\d{1,2}\.\d{1,2}\.(?:-|\s*bis\s*)?\d{1,2}\.\d{1,2}\.20\d\d)")
RX = re.compile(PAT, re.I)

for key, url in SITES.items():
    try:
        r = requests.get(url, headers={"User-Agent": UA},
                         impersonate="chrome120", timeout=25)
        text = re.sub(r"\s+", " ", r.text)
        tm = re.search(r"<title[^>]*>([^<]{0,120})", r.text, re.I)
        title = tm.group(1).strip() if tm else ""
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"key": key, "error": type(exc).__name__}))
        continue
    matches, seen = [], set()
    for m in RX.finditer(text):
        norm = m.group(1)
        if norm in seen:
            continue
        seen.add(norm)
        ctx = text[max(0, m.start() - 70):m.end() + 70]
        matches.append({"date": norm, "context": ctx[-140:]})
        if len(matches) >= 4:
            break
    print(json.dumps({"key": key, "status": r.status_code, "title": title,
                      "dates": matches}))
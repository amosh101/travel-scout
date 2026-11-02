#!/usr/bin/env python3
"""Round-3 news-feed probe — INSIDE api container, final 7 gap cities.

Fresh paths + city-scoped Time Out feeds + national feeds usable with a
city-name ingestion gate (marked gate=True — the runner then requires the
city name in the item text).
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET

from curl_cffi import requests

UA = "travel-scout-probe/1.0 (github.com/amosh101/travel-scout)"
OUT = "/tmp/news_feeds_round3.json"
ITEM_PAT = re.compile(r"<item[\s>]|<entry[\s>]")

# city -> [(outlet, gate_needed, [urls...]), ...]
CANDIDATES = {
    "Munich": [
        ("Süddeutsche München", False, ["https://rss.sueddeutsche.de/app/service/rss/muenchen/index.xml"]),
        ("Süddeutsche", True, ["https://rss.sueddeutsche.de/app/service/rss/alles/index.xml"]),
        ("Abendzeitung München", False, ["https://www.abendzeitung-muenchen.de/feed/rss"]),
    ],
    "Milan": [
        ("Il Messaggero Milano", False, ["https://www.ilmessaggero.it/rss/pagine/milano.xml"]),
        ("Leggo Milano", False, ["https://www.leggo.it/rss/milano.xml", "https://www.leggo.it/rss.xml"]),
        ("AGI Cronaca", True, ["https://www.agi.it/cronaca/rss"]),
    ],
    "Rome": [
        ("Il Messaggero Roma", False, ["https://www.ilmessaggero.it/rss/pagine/roma.xml"]),
        ("Leggo Roma", False, ["https://www.leggo.it/rss/roma.xml"]),
        ("AGI Cronaca", True, ["https://www.agi.it/cronaca/rss"]),
    ],
    "Geneva": [
        ("Swissinfo", True, ["https://www.swissinfo.ch/eng/rss/all", "https://www.swissinfo.ch/eng/rss/latest-news.xml", "https://www.swissinfo.ch/eng/rss"]),
        ("Geneva Business News", False, ["https://genevabusinessnews.com/feed/", "https://www.genevabusinessnews.com/feed/"]),
    ],
    "Zurich": [
        ("Blick", True, ["https://www.blick.ch/news/rss.xml", "https://www.blick.ch/rss.xml"]),
        ("Swissinfo", True, ["https://www.swissinfo.ch/eng/rss/all", "https://www.swissinfo.ch/eng/rss/latest-news.xml"]),
    ],
    "Abu Dhabi": [
        ("Time Out Abu Dhabi", False, ["https://www.timeoutabudhabi.com/feed", "https://www.timeoutabudhabi.com/rss"]),
        ("Khaleej Times", True, ["https://www.khaleejtimes.com/rss/011.xml", "https://www.khaleejtimes.com/rss/feed.xml"]),
    ],
    "Dubai": [
        ("Time Out Dubai", False, ["https://www.timeoutdubai.com/feed", "https://www.timeoutdubai.com/rss"]),
        ("Gulf Today", False, ["https://www.gulftoday.ae/rss/all"]),
        ("Khaleej Times", True, ["https://www.khaleejtimes.com/rss/011.xml"]),
    ],
}


def verify(body: bytes):
    try:
        ET.fromstring(body)
        text = body.decode("utf-8", errors="replace")
        n = len(ITEM_PAT.findall(text))
        return (True, n, None) if n else (False, 0, "no items")
    except ET.ParseError:
        text = body.decode("utf-8", errors="replace")
        n = len(ITEM_PAT.findall(text))
        return (True, n, "malformed-but-real-feed") if n > 0 else (False, 0, "no items")
    except Exception as exc:
        return False, 0, type(exc).__name__


def main() -> int:
    report = {}
    for city, cands in CANDIDATES.items():
        best = None
        tried = []
        for outlet, gate, urls in cands:
            for url in urls:
                rec = {"outlet": outlet, "url": url, "gate": gate}
                try:
                    r = requests.get(url, headers={"User-Agent": UA},
                                     impersonate="chrome120", timeout=25)
                    ok, n, note = verify(r.content)
                    rec.update(ok=ok, items=n, note=note, status=r.status_code)
                except Exception as exc:
                    rec.update(ok=False, note=type(exc).__name__)
                tried.append(rec)
                if rec.get("ok") and best is None:
                    best = rec
                if rec.get("ok"):
                    break
            if best:
                break
        report[city] = {"ok_feed": best, "tried": tried}
        if best:
            g = " gate" if best.get("gate") else ""
            print(f"OK   {city:<11} {best['outlet']:<22} items={best['items']:>4}{g} {best['url'][:78]}")
        else:
            notes = "; ".join(f"{t['outlet']}:{t.get('note') or t.get('status') or '?'}" for t in tried[:3])
            print(f"GAP  {city:<11} {notes[:105]}")
        time.sleep(0.8)
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=1)
    ok = sum(1 for v in report.values() if v["ok_feed"])
    print(f"\nround-3 verified: {ok}/{len(CANDIDATES)}")
    return 0


if __name__ == "__main__":
    main()
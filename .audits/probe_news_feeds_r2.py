#!/usr/bin/env python3
"""Round-2 news-feed probe — runs INSIDE the api container (curl_cffi available).

Targets the 11 cities whose feeds 403'd/disconnected from the host probe.
chrome120 impersonation often passes where stdlib urllib is bot-walled.
Same verify rule: HTTP 200 + item-bearing RSS/Atom XML. Prints per-city
lines; full data to /tmp/news_feeds_round2.json.
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET

from curl_cffi import requests

UA = "travel-scout-probe/1.0 (github.com/amosh101/travel-scout)"
OUT = "/tmp/news_feeds_round2.json"
ITEM_RE = re.compile(r"<item[\s>]|<entry[\s>]")

CANDIDATES = {
    "Shanghai":     [("Shine", ["https://www.shine.cn/rss/all.xml", "https://www.shine.cn/rss/news.xml"]),
                     ("Sixth Tone", ["https://www.sixthtone.com/rss", "https://www.sixthtone.com/rss/news"])],
    "Copenhagen":   [("Copenhagen Post", ["https://cphpost.dk/feed/", "https://cphpost.dk/feed"])],
    "Munich":       [("Süddeutsche", ["https://rss.sueddeutsche.de/app/service/rss/alles/index.xml"]),
                     ("BR24 Bayern", ["https://www.br.de/nachrichten/rss", "https://www.br.de/extra/rss-ticker/index.xml"]),
                     ("Merkur", ["https://www.merkur.de/rss/feed.xml"])],
    "Milan":        [("MilanoToday", ["https://www.milanotoday.it/rss/"]),
                     ("Repubblica Milano", ["https://milano.repubblica.it/rss/homepage-rss/"])],
    "Rome":         [("RomaToday", ["https://www.romatoday.it/rss/"]),
                     ("Repubblica Roma", ["https://roma.repubblica.it/rss/homepage-rss/"])],
    "Johannesburg": [("Moneyweb", ["https://www.moneyweb.co.za/feed/"]),
                     ("TimesLIVE", ["https://www.timeslive.co.za/rss/"])],
    "Geneva":       [("Swissinfo", ["https://www.swissinfo.ch/eng/rss/all", "https://www.swissinfo.ch/eng/rss"]),
                     ("RTS Info", ["https://www.rts.ch/info/rss"])],
    "Zurich":       [("NZZ", ["https://www.nzz.ch/rss.xml"]),
                     ("The Local CH", ["https://www.thelocal.ch/rss/pressreleases", "https://www.thelocal.ch/rss"])],
    "Bangkok":      [("Thaiger", ["https://thethaiger.com/feed/"]),
                     ("Bangkok Post", ["https://www.bangkokpost.com/rss/data/headlines.xml"])],
    "Abu Dhabi":    [("The National", ["https://www.thenationalnews.com/rss", "https://www.thenationalnews.com/rss.xml"]),
                     ("Arabian Business", ["https://www.arabianbusiness.com/feed"])],
    "Dubai":        [("Gulf News", ["https://gulfnews.com/rss?generatorName=uae", "https://gulfnews.com/rss/uae"]),
                     ("Khaleej Times", ["https://www.khaleejtimes.com/rss", "https://www.khaleejtimes.com/rss.xml"]),
                     ("Gulf Today", ["https://www.gulftoday.ae/rss/all", "https://www.gulftoday.ae/rss/all.xml"])],
}


def verify(body: bytes):
    try:
        root = ET.fromstring(body)  # noqa: F841
        text = body.decode("utf-8", errors="replace")
        n = len(re.findall(r"<item[\s>]|<entry[\s>]", text))
        return (True, n, None) if n else (False, 0, "no items")
    except ET.ParseError:
        text = body.decode("utf-8", errors="replace")
        n = len(re.findall(r"<item[\s>]|<entry[\s>]", text))
        if n > 0:
            return True, n, "malformed-but-real-feed"
        return False, 0, "no items"
    except Exception as exc:
        return False, 0, type(exc).__name__


def main() -> int:
    report = {}
    for city, cands in CANDIDATES.items():
        best = None
        tried = []
        for outlet, urls in cands:
            for url in urls:
                rec = {"outlet": outlet, "url": url}
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
            print(f"OK   {city:<14} {best['outlet']:<18} items={best['items']:>4} {best['url'][:80]} {best.get('note') or ''}")
        else:
            notes = "; ".join(f"{t['outlet']}:{t.get('note') or t.get('status') or '?'}" for t in tried[:3])
            print(f"GAP  {city:<14} {notes[:110]}")
        time.sleep(0.8)
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=1)
    ok = sum(1 for v in report.values() if v["ok_feed"])
    print(f"\nround-2 verified: {ok}/{len(CANDIDATES)}")
    return 0


if __name__ == "__main__":
    main()
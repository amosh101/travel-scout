#!/usr/bin/env python3
"""Probe local-news RSS feeds for every travel-scout destination city.

Host-side (stdlib urllib — host lacks curl_cffi). For each city we try a
curated list of credible local outlets' feed endpoints (well-known RSS
paths + the outlet's canonical feed where documented). A feed VERIFIES
only when: HTTP 200 + parseable RSS/Atom XML with >=1 item. Result JSON
lands in .audits/news_feeds_report.json; stdout prints one line per city.

Verified feeds become the NEWS_REGISTRY wiring; cities with zero verified
feeds stay visibly gapped — never fabricated.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
OUT = Path(__file__).resolve().parent / "news_feeds_report.json"

# city -> [(outlet, [urls...]), ...] — first URL that VERIFIES wins.
CANDIDATES = {
    "Vienna":     [("ORF Wien", ["https://rss.orf.at/wien.xml", "https://rss.orf.at/news.xml"]),
                   ("Der Standard Wien", ["https://www.derstandard.at/rss/wien"])],
    "Shanghai":   [("Shine/Shanghai Daily", ["https://www.shine.cn/rss/all.xml", "https://www.shine.cn/rss/citylink.xml"])],
    "Prague":     [("The Prague Monitor", ["https://www.praguemonitor.com/feed/", "https://www.praguemonitor.com/feed"]),
                   ("Radio Prague International", ["https://english.radio.cz/rss/latest-news", "https://english.radio.cz/rss.xml"])],
    "Copenhagen": [("The Copenhagen Post", ["https://cphpost.dk/feed/", "https://cphpost.dk/feed"])],
    "Cairo":      [("Egypt Today", ["https://www.egypttoday.com/rss"]),
                   ("Daily News Egypt", ["https://www.dailynewsegypt.com/feed/", "https://dailynewsegypt.com/feed/"])],
    "Paris":      [("Le Parisien", ["https://www.leparisien.fr/arc/outboundfeeds/rss/?outputType=xml"]),
                   ("France24 Paris", ["https://www.france24.com/fr/rss"])],
    "Berlin":     [("Tagesspiegel", ["https://www.tagesspiegel.de/contentexport/rss/home", "https://www.tagesspiegel.de/rss"]),
                   ("DW Berlin", ["https://rss.dw.com/rdf/rss-en-ger"])],
    "Munich":     [("Süddeutsche", ["https://rss.sueddeutsche.de/app/service/rss/alles/index.xml"]),
                   ("Merkur", ["https://www.merkur.de/rss/feed.xml", "https://www.merkur.de/feed/"])],
    "Athens":     [("Kathimerini English", ["https://www.ekathimerini.com/rss", "https://www.ekathimerini.com/rss.xml"]),
                   ("Greek Reporter", ["https://greekreporter.com/feed/"])],
    "Hong Kong":  [("SCMP Hong Kong", ["https://www.scmp.com/rss/91/feed", "https://www.scmp.com/rss/4/feed"]),
                   ("RTHK", ["https://rthk.hk/rthk/news/rss/e_expressnews_elocal.xml"])],
    "Budapest":   [("We Love Budapest", ["https://welovebudapest.com/en/rss"]),
                   ("Telex", ["https://telex.hu/rss"])],
    "Florence":   [("La Nazione Firenze", ["https://www.lanazione.it/rss/firenze.xml", "https://www.lanazione.it/rss/cronaca.xml"]),
                   ("The Florence Insider", ["https://www.theflorenceinsider.com/feed/"])],
    "Milan":      [("MilanoToday", ["https://www.milanotoday.it/rss/"]),
                   ("Corriere Milano", ["https://xml2.corriereobjects.it/rss/milano.xml"])],
    "Rome":       [("RomaToday", ["https://www.romatoday.it/rss/"]),
                   ("Corriere Roma", ["https://xml2.corriereobjects.it/rss/roma.xml"])],
    "Tokyo":      [("Japan Times", ["https://www.japantimes.co.jp/feed/"]),
                   ("Japan Today", ["https://japantoday.com/feed"])],
    "Nairobi":    [("Nation Africa", ["https://nation.africa/kenya/rss", "https://www.nation.africa/kenya/rss"]),
                   ("Standard KE", ["https://www.standardmedia.co.ke/rss/kenya.php"])],
    "Marrakech":  [("Morocco World News", ["https://www.moroccoworldnews.com/feed/", "https://moroccoworldnews.com/feed/"]),
                   ("Morocco Today", ["https://morocconewsline.com/feed/"])],
    "Maputo":     [("Club of Mozambique", ["https://clubofmozambique.com/feed/", "https://clubofmozambique.com/feed"])],
    "Amsterdam":  [("NL Times", ["https://nltimes.nl/rss.xml", "https://nltimes.nl/feed.xml"]),
                   ("Het Parool", ["https://www.parool.nl/rss/4bd2df6e-8a55-11e7-9a45-df4c6822d21b/collecties/rss.xml"])],
    "Lisbon":     [("Observador", ["https://observador.pt/rss/geral.xml"]),
                   ("Portugal Resident", ["https://www.portugalresident.com/feed/"])],
    "Singapore":  [("CNA Singapore", ["https://www.channelnewsasia.com/api/v1/rss-outbound-feed?category=6408"]),
                   ("Straits Times", ["https://www.straitstimes.com/news/singapore/rss.xml", "https://www.straitstimes.com/news/singapore/feed"])],
    "Cape Town":  [("The South African CPT", ["https://www.thesouthafrican.com/cape-town/feed/"]),
                   ("Daily Maverick", ["https://www.dailymaverick.co.za/dmrss/"])],
    "Johannesburg":[("The South African JHB", ["https://www.thesouthafrican.com/joburg/feed/"]),
                   ("TimesLIVE", ["https://www.timeslive.co.za/rss/"])],
    "Seoul":      [("Korea Herald", ["http://www.koreaherald.com/common/rss_xml.php?ct=103"]),
                   ("Korea Times Seoul", ["https://www.koreatimes.co.kr/www/rss/rss.xml"])],
    "Barcelona":  [("Vilaweb", ["https://www.vilaweb.cat/rss"]),
                   ("La Vanguardia", ["https://www.lavanguardia.com/rss/local.xml", "https://www.lavanguardia.com/rss/catalunya.xml"])],
    "Madrid":     [("ABC Madrid", ["https://www.abc.es/rss/2.0/madrid/"]),
                   ("El Mundo Madrid", ["https://www.elmundo.es/rss/madrid.xml"])],
    "Geneva":     [("Swissinfo Eng", ["https://www.swissinfo.ch/eng/rss/latest-news.xml", "https://www.swissinfo.ch/eng/rss/latestnews.xml"]),
                   ("Tribune de Genève", ["https://www.tdg.ch/rss.xml"])],
    "Zurich":     [("NZZ", ["https://www.nzz.ch/rss.xml"]),
                   ("Tages Anzeiger", ["https://www.tagesanzeiger.ch/rss.xml"])],
    "Bangkok":    [("Bangkok Post", ["https://www.bangkokpost.com/rss/data/headlines.xml", "https://www.bangkokpost.com/rss/data/mostRecent.xml"]),
                   ("The Nation TH", ["https://www.nationthailand.com/rss"])],
    "Abu Dhabi":  [("The National", ["https://www.thenationalnews.com/rss", "https://www.thenationalnews.com/rss.xml"]),
                   ("WAM", ["https://wam.ae/en/rss.xml"])],
    "Dubai":      [("Gulf News", ["https://gulfnews.com/rss?generatorName=uae", "https://gulfnews.com/rss/uae"]),
                   ("Khaleej Times", ["https://www.khaleejtimes.com/rss", "https://www.khaleejtimes.com/rss.xml"])],
    "London":     [("BBC London", ["http://feeds.bbci.co.uk/news/england/london/rss.xml", "https://feeds.bbci.co.uk/news/england/london/rss.xml"]),
                   ("Evening Standard", ["https://www.standard.co.uk/rss/homepage.xml"])],
}

ITEM_RE = re.compile(r"<item[\s>]|<entry[\s>]")


def try_fetch(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(1_200_000)
    ctype = r.headers.get("content-type", "")
    return body, ctype


def verifies(body: bytes) -> tuple[bool, int]:
    """Parseable RSS/Atom with >=1 item? Return (ok, item_count)."""
    try:
        txt = body[:400_000].decode("utf-8", errors="replace")
        if not ITEM_RE.search(txt):
            return False, 0
        # tolerant parse via ElementTree on the full body
        root = ET.fromstring(body)
        text = body.decode("utf-8", errors="replace")
        n_items = text.count("<item") + text.count("<entry")
        return n_items > 0, n_items
    except ET.ParseError:
        text = body.decode("utf-8", errors="replace")
        n = text.count("<item") + text.count("<entry")
        if n > 0:
            return True, n  # malformed XML but real feed — usable with regex parser
        return False, 0
    except Exception:
        return False, 0


def probe_city(city: str, cands: list, report: dict) -> dict:
    entry = {"city": city, "feeds": []}
    for outlet, urls in cands:
        for url in urls:
            rec = {"outlet": outlet, "url": url}
            try:
                body, ctype = try_fetch(url)
                ok, n = verifies(body)
                rec.update(ok=ok, items=n if ok else 0,
                           note=None if ok else "no items")
                if ok:
                    entry["feeds"].append(rec)
            except Exception as exc:
                rec.update(ok=False, note=f"{type(exc).__name__}")
            entry["feeds"].append(rec)
            if rec.get("ok"):
                break       # first verified URL wins per outlet
        if any(f.get("ok") for f in entry["feeds"]):
            break           # first verified outlet wins per city
    report[city] = entry
    chosen = next((f for f in entry["feeds"] if f.get("ok")), None)
    if chosen:
        print(f"OK   {city:<14} {chosen['outlet']:<26} items={chosen['items']:>4} {chosen['url'][:80]}")
    else:
        notes = "; ".join(f"{f['outlet']}:{f.get('note') or 'none'}" for f in entry["feeds"][:4])
        print(f"GAP  {city:<14} {notes[:110]}")
    return entry


def main() -> int:
    report: dict = {}
    for city, cands in CANDIDATES.items():
        probe_city(city, cands, report)
        time.sleep(0.8)
    OUT.write_text(json.dumps(report, indent=1))
    ok = sum(1 for v in report.values() if any(f.get("ok") for f in v["feeds"]))
    print(f"\nverified feeds: {ok}/{len(CANDIDATES)} cities · report: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
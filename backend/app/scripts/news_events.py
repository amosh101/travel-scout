#!/usr/bin/env python3
"""Local-news event scanner: registry-driven RSS ingestion for every
destination city (owner ask 2026-10-27: "add local news as sources for
events for all destination cities").

Model mirrors official_marquee.py: runs INSIDE the api container
(docker cp + docker exec -w /app -e PYTHONPATH=/app <api>
python -m app.scripts.news_events), curls each feed with chrome120
impersonation, and upserts future-dated event rows into scraped_events
with source='local-news'. Receipts go to scraped_runs
(scraper='NewsFeeds').

Honesty contract (real-data-audit-policy):
- An item is ingested ONLY when a parseable FUTURE date (today..+150d)
  comes out of its title/description AND it passes the city gate AND it
  names an event-type word. Everything else is COUNTED (undated/gated/
  outside-window/past), never silently dropped, never row-invented.
- The 28 verified local-outlet feeds were probed live 2026-10-27
  (.audits/probe_news_feeds*.py + news_feeds_report.json). Four cities
  whose local RSS is dead (404/403/JS shells: Munich, Geneva, Dubai,
  Abu Dhabi) ride Google-News city-search feeds instead, WITH per-item
  outlet attribution from the <source> tag and via='google-news' marked.
- Feeds are re-fetched LIVE every run; source_url always points at the
  real article. Rows decay at expires_at (14 days) — no stale echo.

Usage:  see module docstring line above (same container dance as marquee).
"""
from __future__ import annotations

import asyncio
import hashlib
import html as html_mod
import json
import logging
import re
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import asyncpg
from curl_cffi import requests

from app.config import get_settings

logger = logging.getLogger("news_events")

UA = "travel-scout-news/1.0 (github.com/amosh101/travel-scout)"
FETCH_TIMEOUT_S = 25
WINDOW_DAYS = 150
EXPIRES_DAYS = 14
MAX_ITEMS_PER_FEED = 120

# city feeds probed live 2026-10-27 (.audits/probe_news_feeds*.py):
# 28 direct local-outlet feeds + 4 Google-News city mirrors where the
# outlet's own RSS is dead (404/403). gate = regex required in the item
# text for national feeds (keeps city relevance); None = city-scoped feed.
NEWS_REGISTRY: dict[str, dict] = {
    "vienna":     dict(city="Vienna", cc="AT", outlet="ORF Wien", url="https://rss.orf.at/wien.xml", gate=None, via="direct"),
    "shanghai":   dict(city="Shanghai", cc="CN", outlet="Sixth Tone", url="https://www.sixthtone.com/rss", gate="Shanghai", via="direct"),
    "prague":     dict(city="Prague", cc="CZ", outlet="Radio Prague Int'l", url="https://english.radio.cz/rss.xml", gate="Prague", via="direct"),
    "copenhagen": dict(city="Copenhagen", cc="DK", outlet="Copenhagen Post", url="https://cphpost.dk/feed/", gate=None, via="direct"),
    "cairo":      dict(city="Cairo", cc="EG", outlet="Daily News Egypt", url="https://www.dailynewsegypt.com/feed/", gate="Cairo", via="direct"),
    "paris":      dict(city="Paris", cc="FR", outlet="France24", url="https://www.france24.com/fr/rss", gate="Paris", via="direct"),
    "berlin":     dict(city="Berlin", cc="DE", outlet="DW", url="https://rss.dw.com/rdf/rss-en-ger", gate="Berlin", via="direct"),
    "munich":     dict(city="Munich", cc="DE", outlet="Google News (Munich)",
                       url="https://news.google.com/rss/search?q=Munich%20Germany%20AND%20(event%20OR%20festival%20OR%20concert)%20when:30d&hl=en-US&gl=US&ceid=US:en",
                       gate=None, via="google-news"),
    "athens":     dict(city="Athens", cc="GR", outlet="Greek Reporter", url="https://greekreporter.com/feed/", gate="Athens", via="direct"),
    "hongkong":   dict(city="Hong Kong", cc="HK", outlet="SCMP HK", url="https://www.scmp.com/rss/91/feed", gate="Hong Kong|Hongkong|HKSAR", via="direct"),
    "budapest":   dict(city="Budapest", cc="HU", outlet="Telex", url="https://telex.hu/rss", gate="Budapest", via="direct"),
    "florence":   dict(city="Florence", cc="IT", outlet="La Nazione Firenze", url="https://www.lanazione.it/rss/firenze.xml", gate=None, via="direct"),
    "milan":      dict(city="Milan", cc="IT", outlet="Il Messaggero Milano", url="https://www.ilmessaggero.it/rss/pagine/milano.xml", gate=None, via="direct"),
    "rome":       dict(city="Rome", cc="IT", outlet="Il Messaggero Roma", url="https://www.ilmessaggero.it/rss/pagine/roma.xml", gate=None, via="direct"),
    "tokyo":      dict(city="Tokyo", cc="JP", outlet="Japan Times", url="https://www.japantimes.co.jp/feed/", gate="Tokyo", via="direct"),
    "nairobi":    dict(city="Nairobi", cc="KE", outlet="Standard KE", url="https://www.standardmedia.co.ke/rss/kenya.php", gate="Nairobi", via="direct"),
    "marrakech":  dict(city="Marrakech", cc="MA", outlet="Morocco Newsline", url="https://morocconewsline.com/feed/", gate="Marrakech", via="direct"),
    "maputo":     dict(city="Maputo", cc="MZ", outlet="Club of Mozambique", url="https://clubofmozambique.com/feed/", gate="Maputo", via="direct"),
    "amsterdam":  dict(city="Amsterdam", cc="NL", outlet="NL Times", url="https://nltimes.nl/rss.xml", gate="Amsterdam", via="direct"),
    "lisbon":     dict(city="Lisbon", cc="PT", outlet="Portugal Resident", url="https://www.portugalresident.com/feed/", gate="Lisbon", via="direct"),
    "singapore":  dict(city="Singapore", cc="SG", outlet="Straits Times SG", url="https://www.straitstimes.com/news/singapore/rss.xml", gate=None, via="direct"),
    "capetown":   dict(city="Cape Town", cc="ZA", outlet="Daily Maverick", url="https://www.dailymaverick.co.za/dmrss/", gate="Cape Town", via="direct"),
    "johannesburg": dict(city="Johannesburg", cc="ZA", outlet="Moneyweb", url="https://www.moneyweb.co.za/feed/", gate="Johannesburg|Joburg|Gauteng", via="direct"),
    "seoul":      dict(city="Seoul", cc="KR", outlet="Korea Times", url="https://www.koreatimes.co.kr/www/rss/rss.xml", gate="Seoul", via="direct"),
    "barcelona":  dict(city="Barcelona", cc="ES", outlet="Vilaweb", url="https://www.vilaweb.cat/rss", gate="Barcelona", via="direct"),
    "madrid":     dict(city="Madrid", cc="ES", outlet="El Mundo Madrid", url="https://www.elmundo.es/rss/madrid.xml", gate=None, via="direct"),
    "geneva":     dict(city="Geneva", cc="CH", outlet="Google News (Geneva)",
                       url="https://news.google.com/rss/search?q=Geneva%20Switzerland%20AND%20(event%20OR%20festival%20OR%20concert)%20when:30d&hl=en-US&gl=US&ceid=US:en",
                       gate=None, via="google-news"),
    "zurich":     dict(city="Zurich", cc="CH", outlet="Blick", url="https://www.blick.ch/news/rss.xml", gate="Zurich", via="direct"),
    "bangkok":    dict(city="Bangkok", cc="TH", outlet="Thaiger", url="https://thethaiger.com/feed/", gate=None, via="direct"),
    "abudhabi":   dict(city="Abu Dhabi", cc="AE", outlet="Google News (Abu Dhabi)",
                       url="https://news.google.com/rss/search?q=Abu%20Dhabi%20AND%20(event%20OR%20festival%20OR%20concert)%20when:30d&hl=en-US&gl=US&ceid=US:en",
                       gate=None, via="google-news"),
    "dubai":      dict(city="Dubai", cc="AE", outlet="Google News (Dubai)",
                       url="https://news.google.com/rss/search?q=Dubai%20AND%20(event%20OR%20festival%20OR%20concert)%20when:30d&hl=en-US&gl=US&ceid=US:en",
                       gate=None, via="google-news"),
    "london":     dict(city="London", cc="GB", outlet="BBC London", url="https://feeds.bbci.co.uk/news/england/london/rss.xml", gate=None, via="direct"),
}

# ---------------- month tables (feed languages: EN DE FR IT ES CA NL HU) ---
_MONTHS: dict[str, int] = {}
for _names, _num in [
    (("january", "february", "march", "april", "may", "june", "july",
      "august", "september", "october", "november", "december"), "en"),
    (("januar", "februar", "märz", "mai", "juni", "juli", "oktober",
      "dezember"), "de"),  # missing shorts resolved via prefix match below
    (("janvier", "février", "fevrier", "mars", "juin", "juillet", "août",
      "aout", "septembre", "octobre", "novembre", "décembre", "decembre"), "fr"),
    (("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
      "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"), "it"),
    (("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
      "agosto", "septiembre", "octubre", "noviembre", "diciembre"), "es"),
    (("gener", "febrer", "març", "marc", "abril", "maig", "juny", "juliol",
      "agost", "setembre", "octubre", "novembre", "desembre"), "ca"),
    (("januari", "februari", "mei", "augustus", "oktober", "desember"), "nl"),
    (("január", "januar", "február", "februar", "március", "marcius",
      "május", "majus", "június", "julius", "augusztus", "szeptember",
      "október", "oktober", "november", "december"), "hu"),
]:
    for _i, _nm in enumerate(_names, start=1):
        if _nm not in _MONTHS:
            _MONTHS[_nm] = _i
_MONTHS.update({
    # prefix-resolvable shorts/irregulars across the wired languages
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "mrt": 3, "mei": 5, "mrz": 3,
})

EVENT_WORDS = re.compile(
    r"\b(festivals?|carnival|concert[is]?|gig|live music|opera|ballet|"
    r"theatre|theater|teatro|musical|exhibition|exhibition|expo|"
    r"conference|summit|congress|forum|fair|gala|premiere|screening|"
    r"tournament|championship|match|final|semifinal|quarterfinal|derby|"
    r"grand prix|rally|regatta|airshow|biennale|triennale|"
    r"art week|design week|fashion week|film festival|food festival|"
    r"street party|parade|procession|fireworks|new year's? eve|"
    r"christmas market|christmas fair|countdown|celebration|opening night|"
    r"carnival parade|light festival|marathon|half-marathon|10k|"
    r"fun run|cycling|bicycle race|boat show|motor show|wine|"
    r"christkindlmarkt)\b", re.I)

# ---------------- date parsing ---------------------------------------------
_D_MONTHNAME = re.compile(
    r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s*(?:de\s*|den\s*|dal\s*)?"
    r"(?P<mon>[A-Za-zÀ-ÿ]{3,12})\b(?:\s*(?:de|d')?\s*(?P<y>20\d\d))?",
    re.I)
_D_MONTHNAME_US = re.compile(
    r"\b(?P<mon>[A-Za-zÀ-ÿ]{3,12})\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?"
    r"\s*[-–]\s*(?P<d2>\d{1,2})?(?:st|nd|rd|th)?"
    r"(?:\s*,\s*(?P<y>20\d\d))?", re.I)
_D_RANGE = re.compile(
    r"\b(?P<d1>\d{1,2})\s*[-–]\s*(?P<d2>\d{1,2})\s+"
    r"(?P<mon>[A-Za-zÀ-ÿ]{3,12})\b(?:\s*(?:de\s*|del\s*)?\s*(?P<y>20\d\d))?",
    re.I)
_D_ISO = re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d\d)-(?P<d>\d\d)\b")
_D_SLASH = re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/20\d\d\b")


def _month(v: str) -> int | None:
    """Month from a name in any wired feed language; tolerant of accents/
    suffixes (gennaio, gennaio, märz, janvier, gener…)."""
    v = v.strip().lower()
    if v in _MONTHS:
        return _MONTHS[v]
    v4 = v[:4]
    if v4 in _MONTHS:
        return _MONTHS[v4]
    return None


def _future(start: date, end: date | None, today: date, horizon: date):
    """Push a parse into the window or return None. Past dates stay past."""
    if end is None:
        if today <= start <= horizon:
            return start
        # year-less mention that already fell away this year -> don't invent
        return None
    if today <= end <= horizon or today <= start <= horizon:
        return start, end
    return None


def parse_dates(text: str, today: date, horizon: date):
    """Return (start, end) for the FIRST window-eligible date in text, else
    None. Explicit-year mentions resolve as written; bare 'March 15' gets
    the upcoming occurrence. Never returns a date outside the window."""
    for pat in (_D_ISO, _D_RANGE, _D_MONTHNAME, _D_MONTHNAME_US, _D_SLASH):
        for m in pat.finditer(text):
            gd = m.groupdict()
            try:
                if pat is _D_ISO:
                    got = (date(int(gd["y"]), int(gd["m"]), int(gd["d"])), None)
                elif pat is _D_SLASH:
                    if int(gd["m"]) > 12:      # ambiguous xx/yy — refuse
                        continue
                    y = int(m.group(0).split("/")[2])
                    got = (date(y, int(gd["m"]), int(gd["d"])), None)
                elif pat is _D_RANGE:
                    mo = _month(gd["mon"])
                    if not mo:
                        continue
                    y = int(gd["y"]) if gd.get("y") else _infer_year(mo, int(gd["d1"]), today)
                    d1, d2 = int(gd["d1"]), int(gd["d2"] or gd["d1"])
                    if d2 < d1:
                        continue
                    got = (date(y, mo, d1), date(y, mo, d2))
                elif pat is _D_MONTHNAME_US:
                    mo = _month(gd["mon"])
                    if not mo:
                        continue
                    y = int(gd["y"]) if gd.get("y") else _infer_year(mo, int(gd["d"]), today)
                    d2 = int(gd["d2"]) if gd.get("d2") else None
                    end = date(y, mo, d2) if d2 and d2 > int(gd["d"]) else None
                    got = (date(y, mo, int(gd["d"])), end)
                else:  # _D_MONTHNAME
                    mo = _month(gd["mon"])
                    if not mo:
                        continue
                    if int(gd["d"]) > 31:
                        continue
                    y = int(gd["y"]) if gd.get("y") else _infer_year(mo, int(gd["d"]), today)
                    got = (date(y, mo, int(gd["d"])), None)
                break_ = _future(got[0], got[1], today, horizon)
                if break_:
                    return (break_ if isinstance(break_, tuple)
                            else (break_, break_))
            except ValueError:
                continue
    return None


def _infer_year(month: int, day: int, today: date) -> int:
    """No explicit year: pick the NEXT occurrence of this month/day.
    If the exact upcoming occurrence already lies beyond +150d window,
    _future() rejects it — nothing invented beyond that."""
    cand = date(today.year, month, day)
    if cand < today:
        cand = date(today.year + 1, month, day)
    return cand.year


# ---------------- feed fetch + parse --------------------------------------
def fetch_feeds(entry: dict, rounds: int = 2) -> str:
    last: Exception | None = None
    for i in range(rounds):
        try:
            r = requests.get(entry["url"], headers={"User-Agent": UA},
                             impersonate="chrome120", timeout=FETCH_TIMEOUT_S)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001
            last = exc
            if i < rounds - 1:
                time.sleep(4)
    raise RuntimeError(f"{type(last).__name__}: {last}")


def _strip_html(s: str) -> str:
    return html_mod.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def parse_items(xml_text: str, entry: dict, limit: int):
    """Yield dicts {title, link, pub, desc, outlet_name, outlet_url} from
    RSS2 <item> or Atom <entry> elements. Tolerant of slight malformedness
    (falls back to a regex crack when the tree won't build)."""
    items = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
        for el in root.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "item":
                title = (el.findtext("title") or "").strip()
                link = (el.findtext("link") or "").strip()
                if not link:
                    link = ((el.findtext("{*}link") or "").strip())
                pub = (el.findtext("pubDate") or el.findtext("date") or
                       el.findtext("{*}date") or "").strip()
                desc = _strip_html(el.findtext("description") or
                                   el.findtext("{*}summary") or "")
                src = el.find("source")
                oname = (src.text or "").strip() if src is not None else ""
                ourl = src.get("url", "") if src is not None else ""
                if title:
                    items.append(dict(title=title, link=link, pub=pub,
                                      desc=desc, outlet_name=oname,
                                      outlet_url=ourl))
            elif tag == "entry":
                title = (el.findtext("{*}title") or "").strip()
                link = ""
                for l in el.findall("{*}link"):
                    if l.get("rel") in (None, "alternate") and l.get("href"):
                        link = l.get("href")
                        break
                pub = (el.findtext("{*}updated") or
                       el.findtext("{*}published") or "").strip()
                desc = _strip_html(el.findtext("{*}summary") or
                                   el.findtext("{*}content") or "")
                if title:
                    items.append(dict(title=title, link=link, pub=pub,
                                      desc=desc, outlet_name="", outlet_url=""))
    except ET.ParseError:
        # malformed-but-real feed: crack with regex, best effort
        for chunk in re.findall(r"<item[\s>].*?</item>|<entry[\s>].*?</entry>",
                                xml_text, re.S)[:limit]:
            title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>",
                              chunk, re.S)
            link = re.search(r"<link[^>]*href=[\"']([^\"']+)|<link>(?:<!\[CDATA\[)?"
                             r"([^\]<!]+)", chunk)
            pub = re.search(r"<(?:pubDate|updated|published)>(.*?)</", chunk, re.S)
            if title:
                items.append(dict(
                    title=html_mod.unescape(title.group(1)).strip(),
                    link=(link.group(1) or link.group(2)).strip() if link else "",
                    pub=pub.group(1).strip() if pub else "",
                    desc=_strip_html(re.search(r"<description>(.*?)</description>",
                                               chunk, re.S).group(1))
                    if re.search(r"<description>", chunk) else "",
                    outlet_name="", outlet_url=""))
    return items[:limit]


def _strip_outlet_suffix(title: str, outlet: str) -> str:
    tail = f" - {outlet}"
    if outlet and title.endswith(tail):
        return title[: -len(tail)].strip()
    return title


# ---------------- db helpers (mirror official_marquee) ---------------------
async def ensure_location(conn, city, cc, now, expires):
    return await conn.fetchval(
        """INSERT INTO scraped_locations
             (id, source, source_id, name, country_alpha2, scraped_at,
              expires_at)
           VALUES ($1,'location_resolver',$2,$3,$4,$5,$6)
           ON CONFLICT (source, source_id) DO UPDATE
             SET scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
           RETURNING id""",
        uuid.uuid4(), f"{cc}:{city}", city, cc, now, expires)


async def upsert_event(conn, entry, title, start, end, item, now, expires,
                       match_date_note):
    source_id = f"{entry['slug']}|{hashlib.md5((item['link'] or title).encode()).hexdigest()[:16]}"
    raw = {
        "source_url": item["link"],
        "outlet": item.get("outlet_name") or entry["outlet"],
        "outlet_url": item.get("outlet_url") or (entry["url"] if entry["via"] == "direct" else ""),
        "city": entry["city"], "country": entry["cc"],
        "via": entry["via"], "sweep": "news-feeds",
        "pub_date": item.get("pub") or None,
        "date_note": match_date_note,
    }
    return await conn.fetchval(
        """INSERT INTO scraped_events
             (id, source, source_id, name, kind, interest_key, starts_at,
              ends_at, location_id, wikidata_qid, raw, scraped_at,
              expires_at, dedupe_year)
           VALUES ($1,'local-news',$2,$3,'event','city-sweep',$4,$5,
                   (SELECT id FROM scraped_locations
                     WHERE source='location_resolver' AND source_id=$6),
                   '', $7::jsonb, $8, $9, $10)
           ON CONFLICT (source, source_id, dedupe_year) DO UPDATE
             SET name=EXCLUDED.name, starts_at=EXCLUDED.starts_at,
                 ends_at=EXCLUDED.ends_at, raw=EXCLUDED.raw,
                 scraped_at=EXCLUDED.scraped_at, expires_at=EXCLUDED.expires_at
           RETURNING (xmax = 0)""",
        uuid.uuid4(), source_id, title[:300], start, end,
        f"{entry['cc']}:{entry['city']}", json.dumps(raw),
        now, expires, start.year)


# ---------------- runner ---------------------------------------------------
async def run() -> dict:
    started_at = datetime.now(timezone.utc)
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    today = date.today()
    horizon = today + timedelta(days=WINDOW_DAYS)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=EXPIRES_DAYS)

    added = updated = errors = 0
    per_city: dict[str, str] = {}
    try:
        locs = {
            (e["cc"], e["city"]): await ensure_location(
                conn, e["city"], e["cc"], now, expires)
            for e in NEWS_REGISTRY.values()
        }
        for slug, entry in NEWS_REGISTRY.items():
            e2 = {**entry, "slug": slug}
            try:
                xml_text = fetch_feeds(e2)
            except Exception as exc:  # noqa: BLE001
                errors += 1
                per_city[e2["city"]] = f"fetch_failed {type(exc).__name__}"
                logger.warning("news feed failed %s: %s", slug, exc)
                continue
            items = parse_items(xml_text, e2, MAX_ITEMS_PER_FEED)
            if not items:
                # transient empty/variant body seen 2026-10-27 on the DW RDF
                # feed (refetch parses fine): retry once before declaring
                try:
                    xml_text = fetch_feeds(e2)
                    items = parse_items(xml_text, e2, MAX_ITEMS_PER_FEED)
                except Exception:  # noqa: BLE001 - fall through with []
                    items = []
                if not items:
                    per_city[e2["city"]] = "parse_empty (transient feed body?)"
                    continue
            scanned = gated = undated = outside = past = ing = 0
            gate_re = re.compile(e2["gate"], re.I) if e2.get("gate") else None
            for item in items:
                scanned += 1
                text = f"{item['title']} {item['desc']}"
                if gate_re and not gate_re.search(text):
                    gated += 1
                    continue
                if not EVENT_WORDS.search(text):
                    continue          # plain news, not event-ish (not counted)
                got = parse_dates(text, today, horizon)
                if not got:
                    undated += 1
                    continue
                start, end = got
                if start < today:
                    past += 1
                    continue
                if start > horizon:
                    outside += 1
                    continue
                title = _strip_outlet_suffix(item["title"],
                                             item.get("outlet_name") or "")
                is_new = await upsert_event(
                    conn, e2, title, start, end or start, item, now, expires,
                    "event date parsed from headline/description; "
                    "verify at the source article before relying on it")
                ing += 1
                added += 1 if is_new else 0
                updated += 0 if is_new else 1
            per_city[e2["city"]] = (f"scanned={scanned} ingested={ing} "
                                    f"undated={undated} gated={gated} "
                                    f"past={past} outside={outside}")
        finished_at = datetime.now(timezone.utc)
        scraped = added + updated
        status = "error" if errors and not scraped else "success"
        await conn.execute(
            """INSERT INTO scraped_runs
                 (id, source, scraper, started_at, finished_at, status,
                  added, updated, error, duration_ms)
               VALUES ($1,'local-news','NewsFeeds',$2,$3,$4,$5,$6,
                       $7,$8)""",
            uuid.uuid4(), started_at, finished_at, status,
            added, updated,
            None if not errors else f"{errors} feed fetch error(s)",
            int((finished_at - started_at).total_seconds() * 1000))
        return {"status": "done", "added": added, "updated": updated,
                "errors": errors, "cities": len(NEWS_REGISTRY),
                "per_city": per_city}
    finally:
        await conn.close()


def main() -> None:
    print(json.dumps(asyncio.run(run()), indent=2))


if __name__ == "__main__":
    main()
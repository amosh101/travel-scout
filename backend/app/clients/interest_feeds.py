"""Deep interest-event harvest: magazines, blogs, newspapers, social.

Wired after the free-events aggregator. Every source here was PROBED
LIVE before inclusion (see git history — feeds that 404'd or
rate-limit-blocked were deliberately excluded: jazztimes, timeout,
timeslive, motorsport.com's old RSS path).

Design rules:
- REAL DATA ONLY. An article becomes an event only when we can parse
  an explicit event date out of its text. Publish dates are NEVER used
  as event dates (a feed item published today is not an event today).
- City/country placement must appear in the item text; unmatched items
  are skipped and counted in the returned notes (honest missing[]).
- Replicable: stable curated registry, fixed parse rules, deterministic
  ordering, per-feed in-process cache (1 h) so repeated searches with
  the same inputs see the same source payloads.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import httpx

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 8.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}
_FETCH_SEM = asyncio.Semaphore(3)


async def _fetch_feed(url: str) -> str | None:
    """GET a feed's raw XML. None on any failure (caller counts it)."""
    try:
        async with _FETCH_SEM, httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, headers=_HEADERS, follow_redirects=True,
        ) as client:
            r = await client.get(url)
            if r.status_code != 200:
                logger.info("Feed %s -> HTTP %s", url, r.status_code)
                return None
            return r.text
    except Exception as e:  # noqa: BLE001
        logger.info("Feed %s failed: %s", url, e)
        return None


# -----------------------------------------------------------------------------
# Curated registry — vertical -> feeds. All verified live on 2026-10-21.
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Feed:
    key: str            # stable id for source labels
    url: str
    title: str
    feeds: tuple[str, ...] = field(default=())  # verticals this feed serves


BBC = "https://feeds.bbci.co.uk"
GUARD = "https://www.theguardian.com"

REGISTRY: tuple[Feed, ...] = (
    # motorsport
    Feed("autosport", "https://www.autosport.com/rss/all/news/", "Autosport", ("motorsport",)),
    Feed("therace", "https://www.the-race.com/feed/", "The Race", ("motorsport",)),
    Feed("bbc-f1", f"{BBC}/sport/formula1/rss.xml", "BBC Sport F1", ("motorsport",)),
    Feed("reddit-f1", "https://www.reddit.com/r/formula1/new/.rss", "r/formula1", ("motorsport",)),
    # music (jazz / electronic / afrobeat / hip-hop / rock / classical / nightlife)
    Feed("guardian-music", f"{GUARD}/music/rss", "The Guardian Music", ("music",)),
    Feed("pitchfork", "https://pitchfork.com/rss/news/", "Pitchfork", ("music",)),
    Feed("djmag", "https://djmag.com/rss.xml", "DJ Mag", ("music",)),
    # food / wine
    Feed("guardian-food", f"{GUARD}/food/rss", "The Guardian Food", ("food",)),
    Feed("eater", "https://www.eater.com/rss/index.xml", "Eater", ("food",)),
    # art / design / photography / architecture / fashion
    Feed("guardian-art", f"{GUARD}/artanddesign/rss", "The Guardian Art & Design", ("art",)),
    Feed("designboom", "https://www.designboom.com/feed/", "designboom", ("art",)),
    # literature
    Feed("guardian-books", f"{GUARD}/books/rss", "The Guardian Books", ("books",)),
    # theatre / comedy
    Feed("guardian-stage", f"{GUARD}/stage/rss", "The Guardian Stage", ("stage",)),
    # film
    Feed("guardian-film", f"{GUARD}/film/rss", "The Guardian Film", ("film",)),
    # travel / adventure / outdoors
    Feed("guardian-travel", f"{GUARD}/travel/rss", "The Guardian Travel", ("travel",)),
    # sport generally (football, cycling, running, esports ...)
    Feed("guardian-sport", f"{GUARD}/uk/sport/rss", "The Guardian Sport", ("sport",)),
    Feed("bbc-football", f"{BBC}/sport/football/rss.xml", "BBC Sport Football", ("sport",)),
    # regional newspapers / magazines (local coverage for our markets)
    Feed("clubofmozambique", "https://www.clubofmozambique.com/feed/", "Club of Mozambique", ("localsahara",)),
    Feed("newsday-zw", "https://www.newsday.co.zw/feed", "NewsDay Zimbabwe", ("localsahara",)),
    Feed("dailymaverick", "https://www.dailymaverick.co.za/dmrss/", "Daily Maverick", ("localsahara",)),
)

FEEDS_BY_KEY = {f.key: f for f in REGISTRY}

# Interest CATALOG keys (the same keys the interests table stores and
# the intake flow sends) mapped to feed verticals. Anything unmapped
# (casino, poker, luxury ...) gets no deep sources — reported honestly.
KEY_TO_VERTICALS: dict[str, tuple[str, ...]] = {
    "f1": ("motorsport",), "motorsport": ("motorsport",), "racing": ("motorsport",),
    "jazz": ("music",), "live-jazz": ("music",), "world-music": ("music",),
    "electronic-music": ("music",), "afrobeat": ("music",), "amapiano": ("music",),
    "hip-hop": ("music",), "latin": ("music",), "rock": ("music",),
    "classical": ("music",), "opera": ("music", "stage"), "dance": ("music", "stage"),
    "nightlife": ("music",),
    "food-wine": ("food",), "wine": ("food",), "beer": ("food",), "coffee": ("food",),
    "champagne": ("food",), "whisky": ("food",), "caviar": ("food",),
    "art-museums": ("art",), "modern-art": ("art",), "renaissance-art": ("art",),
    "photography": ("art",), "architecture": ("art",), "design": ("art",),
    "fashion": ("art",),
    "literature": ("books",),
    "theatre": ("stage",), "comedy": ("stage",),
    "film": ("film",),
    "adventure": ("travel",), "kite-surfing": ("travel",), "wellness": ("travel",),
    "skiing": ("travel",),
    "football": ("sport",), "golf": ("sport",), "cycling": ("sport",),
    "marathon": ("sport",), "esports": ("sport",), "horse-racing": ("sport",),
    "sailing": ("sport",), "shooting": ("sport",), "tennis": ("sport",),
    "wimbledon": ("sport",), "urban": ("sport", "music"),
}

_TOKEN_KW_FALLBACK: dict[str, tuple[str, ...]] = {
    "motorsport": ("f1", "motorsport", "formula", "racing", "grand prix"),
    "music": ("music", "jazz", "concert", "gig", "afrobeat", "amapiano", "hip-hop",
              "hip hop", "rap", "soul", "funk", "disco", "techno", "house", "edm",
              "dj", "band", "album", "opera", "classical", "orchestra"),
    "food": ("food", "wine", "whisky", "champagne", "beer", "coffee", "gastronomy",
             "restaurant", "chef", "dining"),
    "art": ("art", "museum", "gallery", "exhibition", "design", "architecture",
            "photography", "fashion", "biennale"),
    "books": ("literature", "book", "novel", "poetry", "author"),
    "stage": ("theatre", "theater", "comedy", "standup", "stage", "play", "musical"),
    "film": ("film", "cinema", "movie", "screening", "festival"),
    "travel": ("travel", "adventure", "outdoor", "hiking", "surfing", "wellness",
               "spa", "safari", "skiing", "beach"),
    "sport": ("football", "soccer", "sport", "cycling", "tennis", "golf", "rugby",
              "cricket", "marathon", "esports", "racing", "cup", "match"),
}


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "")).lower().strip()
    # Accent-fold: refdata carries "São Paulo" while feeds often write
    # "Sao Paulo" — compare folded forms.
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def verticals_for_interest(name: str) -> set[str]:
    """Map an interest (catalog KEY first, display-name fallback) to the
    feed verticals that may serve it. Returns {'localsahara'} at minimum —
    regional press gates on city/country mention + event wording.
    """
    n = _norm(name)
    verts: set[str] = set()
    exact = KEY_TO_VERTICALS.get(n)
    if exact:
        verts.update(exact)
    else:
        for vert, kws in _TOKEN_KW_FALLBACK.items():
            for kw in kws:
                if re.search(r"\b%s\b" % re.escape(kw), n):
                    verts.add(vert)
                    break
    verts.add("localsahara")
    return verts


# Back-compat alias used in older callers.
_verticals_for_interest = verticals_for_interest

EVENT_WORDS = (
    "festival", "concert", "gala", "exhibition", "premiere", "grand prix", "race",
    "tour", "show", "gig", "opening", "biennale", "carnival", "parade", "market",
    "celebration", "summit", "awards", "championship", "cup final", "marathon",
    "weekender", "weekend guide", "things to do", "what's on",
)

_MONTHS = {
    m.lower(): i + 1
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"]
    )
}
for _m in list(_MONTHS):
    _MONTHS[_m[:3]] = _MONTHS[_m]

_DATE_PATTERNS = (
    # 2026-11-04
    re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b"),
    # 12 November 2027 / 12th of November 2027
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:of )?(%s) (20\d\d)\b" % "|".join(_MONTHS), re.I),
    # November 12, 2027 / Nov 12 2027
    re.compile(r"\b(%s) (\d{1,2})(?:st|nd|rd|th)?,? (20\d\d)\b" % "|".join(_MONTHS), re.I),
    # 12/11/2026 (day-first in the markets we serve)
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b"),
)


def _parse_event_date(text: str) -> date | None:
    """Parse the FIRST explicit absolute date in the text. No year -> None."""
    m = None
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            break
    if not m:
        return None
    g = [(int(s) if s.isdigit() else s.lower()) for s in m.groups()]
    try:
        if isinstance(g[0], int) and g[0] > 1000:  # YYYY-MM-DD
            return date(int(g[0]), int(g[1]), int(g[2]))
        if isinstance(g[1], str):  # 12 November 2027
            return date(int(g[2]), int(_MONTHS[str(g[1])]), int(g[0]))
        if isinstance(g[0], str):  # November 12, 2027
            return date(int(g[2]), int(_MONTHS[str(g[0])]), int(g[1]))
        return date(int(g[2]), int(g[1]), int(g[0]))  # 12/11/2026 (day-first)
    except (ValueError, KeyError):
        return None
    return None


# -----------------------------------------------------------------------------
# Feed parsing (RSS 2 + Atom, stdlib only)
# -----------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


@dataclass
class RawItem:
    title: str
    link: str
    summary: str
    published: datetime | None


def _parse_feed(xml_text: str, cap: int = 60) -> list[RawItem]:
    try:
        root = ET.fromstring(xml_text[:2_000_000])
    except ET.ParseError:
        return []
    items: list[RawItem] = []
    for el in root.iter():
        tag = _strip_ns(el.tag)
        if tag == "item":
            title, link, summary, pub = "", "", "", None
            for ch in el:
                t = _strip_ns(ch.tag)
                if t == "title" and ch.text:
                    title = html_mod.unescape(ch.text)
                elif t == "link":
                    link = (ch.text or "").strip() or (ch.get("href") or "")
                elif t in ("description", "summary", "content:encoded") and ch.text and not summary:
                    summary = ch.text
                elif t in ("pubDate", "published", "updated", "date") and ch.text:
                    pub = _parse_http_date(ch.text)
            if title:
                items.append(RawItem(title, link, summary, pub))
        elif tag == "entry":  # Atom
            title, link, summary, pub = "", "", "", None
            for ch in el:
                t = _strip_ns(ch.tag)
                if t == "title" and ch.text:
                    title = html_mod.unescape(ch.text)
                elif t == "link" and (ch.get("href") or ""):
                    link = ch.get("href") or ""
                elif t in ("summary", "content") and ch.text and not summary:
                    summary = ch.text
                elif t in ("published", "updated") and ch.text:
                    pub = _parse_http_date(ch.text)
            if title:
                items.append(RawItem(title, link, summary, pub))
    return items[:cap] if cap else items


def _parse_http_date(s: str) -> datetime | None:
    s = s.strip()
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    m = re.match(r"(\d{4}-\d\d-\d\d)", s)
    if m:
        try:
            return datetime.fromisoformat(m.group(1))
        except ValueError:
            return None
    return None


# -----------------------------------------------------------------------------
# Cache + event extraction
# -----------------------------------------------------------------------------

# (feed_key) -> (fetch_ts, [RawItem]); process-local, like free_events.
_FEED_CACHE: dict[str, tuple[float, list[RawItem]]] = {}
_FEED_TTL_S = 3600.0


def clear_caches() -> None:
    _FEED_CACHE.clear()


async def _items_for(feed: Feed) -> list[RawItem]:
    import time
    cached = _FEED_CACHE.get(feed.key)
    if cached and (time.monotonic() - cached[0]) < _FEED_TTL_S:
        return cached[1]
    xml_text = await _fetch_feed(feed.url)
    items = _parse_feed(xml_text) if xml_text else []
    _FEED_CACHE[feed.key] = (time.monotonic(), items)
    return items


def _eventish(item: RawItem) -> bool:
    text = _norm(f"{item.title} {item.summary}")
    return any(w in text for w in EVENT_WORDS)


def _mentions_place(text: str, city: str, country: str | None) -> bool:
    if city and city.lower() in text:
        return True
    if country and len(country) > 3 and country.lower() in text:
        return True
    return False


async def search_for_trip(
    interest_names: list[str],
    *,
    city: str,
    country: str | None,
    start_date: date,
    end_date: date,
    limit_per_interest: int = 4,
) -> tuple[list[dict], list[str]]:
    """Harvest deep-source events for ONE trip candidate.

    Returns (events, notes) where events match the anchor_events dict
    shape used by the builder, every event is dated + verified in-text
    for the trip's place, and notes list honest coverage gaps for
    missing[].
    """
    if not interest_names:
        return [], []

    events: list[dict] = []
    notes: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    wanted_verts: set[str] = set()
    for name in interest_names:
        wanted_verts |= _verticals_for_interest(name)
    # Verticals minus the always-on regional press feed set.
    feed_keys = [
        f.key for f in REGISTRY
        if f.feeds and (set(f.feeds) & (wanted_verts - {"localsahara"}))
    ]
    local_keys = [f.key for f in REGISTRY if "localsahara" in f.feeds]
    # Regional press is only useful when it can place the trip — include
    # but gate hard on city/country mention below.
    feed_keys += local_keys

    skips = {"city_unmatched": 0, "no_date": 0, "not_eventish": 0, "feed_failed": 0,
             "not_interest": 0}

    async def harvest(feed: Feed) -> None:
        items = await _items_for(feed)
        if not items:
            skips["feed_failed"] += 1
            return
        for it in items:
            text = _norm(f"{it.title} {it.summary}")
            if not _eventish(it):
                skips["not_eventish"] += 1
                continue
            # Relevance: curated feed vertical OR interest keyword in item.
            if feed.feeds and set(feed.feeds) & {"localsahara"} and not (
                wanted_verts - {"localsahara"}
            ):
                skips["not_interest"] += 1
                continue
            if not (_mentions_place(text, city, country)):
                skips["city_unmatched"] += 1
                continue
            ev_date = _parse_event_date(text)
            if ev_date is None or not (start_date <= ev_date <= end_date):
                skips["no_date"] += 1
                continue
            key = (_norm(it.title)[:80], ev_date.isoformat(), city.lower())
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "kind": "feed_event",
                "title": it.title,
                "date": ev_date.isoformat(),
                "city": city,
                "country": country or "",
                "source": f"rss:{feed.title}",
                "source_url": it.link or feed.url,
                # publish date kept for provenance/debug only — never
                # used as the event date.
                "note": "from_press_feed",
            })

    results = await asyncio.gather(*(harvest(FEEDS_BY_KEY[k]) for k in feed_keys if k in FEEDS_BY_KEY))
    _ = results

    # Relevance guard: an event may only enter if one of the SELECTED
    # interests shares a vertical with its source feed. (Items from the
    # regional-press 'localsahara' feeds additionally had to mention the
    # trip's city/country in their text to reach this stage.)
    kept: list[dict] = []
    for e in events:
        src = e.get("source", "")
        feed = next((f for f in REGISTRY if src == f"rss:{f.title}"), None)
        matched = False
        for name in interest_names:
            if feed and feed.feeds and (set(feed.feeds) & verticals_for_interest(name)):
                matched = True
                break
        if matched:
            kept.append(e)
        else:
            skips["not_interest"] += 1

    kept.sort(key=lambda e: (e.get("date") or "", e.get("title") or ""))
    if len(kept) > limit_per_interest * len(interest_names):
        kept = kept[: limit_per_interest * len(interest_names)]
    # Notes (2026-10-22 rewording, Sir: the three-line skip-accounting
    # read as "the feature is broken"). Keep it short and honest:
    # mention only real failures, and only in a single line when the
    # harvest came up empty.
    if skips["feed_failed"]:
        notes.append(
            f"{skips['feed_failed']} press feed(s) couldn't be reached this run"
        )
    if not kept:
        notes.append(
            "no dated local listings in press/magazine feeds this window "
            "(races, holidays and event-database results still shown above)"
        )
    return kept, notes
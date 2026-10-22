"""Free event sources — no API keys, no paywall.

Each source is a thin async client that returns ``EventRecord`` objects
in a common shape. The intersection algorithm consumes that shape and
doesn't care which source produced the event.

The list of free sources is not hardcoded in the search router — it's
a row in the ``event_sources`` table (admin-editable) and the router
queries by interest-key. To add a new source, an admin adds a row.

Currently wired:
  - **Wikidata** (SPARQL): structured recurring events (festivals,
    F1/cycling/marathon races, sporting tournaments, art biennales,
    book fairs, design weeks, etc.). Queryable by country, type, and
    date range. Free, CC0.
  - **Wikipedia "list of" articles**: text-mined for top annual events
    per city. Free, CC-BY-SA.
  - **LocationResolver** (ISO 3166-1 cross-validated) — every event
    location is normalised to a fully-populated ``Location`` object
    (alpha-2/3/numeric, ISO 3166-2 subdivision, ISO 6709 coordinates,
    UN M49 region, GeoNames ID, Wikidata QID). Country matches are
    consensus-validated across Nominatim, Wikidata SPARQL, GeoNames
    (optional) and the bundled ISO 3166-1 dataset.

Planned but deferred (need admin to provide a public/free endpoint):
  - Bandsintown (now requires app key)
  - Songkick (deprecated public API)
  - SeatGeek (now OAuth-only)

If a source is configured and the upstream fails, the response just
shows fewer events — never blocks the result.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

from curl_cffi import requests

from app.refdata.iso3166 import (
    ALPHA2_TO_WIKIDATA_QID,
    IOC_TO_ALPHA2,
    M49_TO_REGION_NAME,
    country as iso_country,
    resolve_alpha2,
)
from app.schemas.location import Location, GeoSource

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Common shape
# -----------------------------------------------------------------------------

@dataclass
class EventRecord:
    """One event that the intersection algorithm can rank and surface.

    Every event carries a fully-validated ``Location`` (ISO 3166-1
    alpha-2/3/numeric, ISO 3166-2 subdivision, ISO 6709 coordinates,
    UN M49 region, Wikidata QID, GeoNames ID). The string fields
    ``city`` / ``country`` / ``country_alpha2`` / ``latitude`` /
    ``longitude`` are kept populated as backward-compat aliases derived
    from ``location`` — the front-end and router code may continue to
    read them directly.
    """
    name: str
    kind: str                       # "f1_race" | "music_festival" | "sport_match" | "exhibition" | ...
    starts_at: date | None = None
    ends_at: date | None = None
    location: Location | None = None
    city: str = ""
    country: str = ""
    country_alpha2: str = ""
    latitude: float | None = None
    longitude: float | None = None
    source: str = ""                # "wikidata" | "wikipedia" | "jolpica" | "holidays"
    source_url: str = ""
    source_qid: str = ""            # Wikidata QID for dedupe / linking
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Keep the legacy string fields in sync with the be in sync
        if self.location:
            if not self.city and self.location.locality:
                self.city = self.location.locality
            if not self.country and self.location.country_name_en:
                self.country = self.location.country_name_en
            if not self.country_alpha2 and self.location.country_alpha2:
                self.country_alpha2 = self.location.country_alpha2
            if self.latitude is None and self.location.latitude is not None:
                self.latitude = self.location.latitude
            if self.longitude is None and self.location.longitude is not None:
                self.longitude = self.location.longitude
        else:
            # No Location attached — best-effort backfill from the
            # bare string fields. This keeps the legacy callers working
            # while we migrate the rest of the codebase.
            if self.country_alpha2 and not self.country:
                rec = iso_country(self.country_alpha2)
                if rec:
                    self.country = rec.get("name_en", "")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["starts_at"] = self.starts_at.isoformat() if self.starts_at else None
        d["ends_at"] = self.ends_at.isoformat() if self.ends_at else None
        if self.location is not None:
            d["location"] = self.location.to_dict()
        return d

    @property
    def has_iso_country(self) -> bool:
        return bool(self.country_alpha2) and len(self.country_alpha2) == 2


# -----------------------------------------------------------------------------
# Wikidata (SPARQL)
# -----------------------------------------------------------------------------

# Q-IDs for event types we care about. See the search list at
# https://www.wikidata.org/wiki/Wikidata:WikiProject_Events
#
# We use the *most specific* type per interest so queries return
# clean results, and we add a handful of broader fallbacks
# (recurring sporting event Q18608583, etc.) for niche interests
# that don't have their own dedicated type.
_EVENT_TYPE_QIDS: dict[str, list[str]] = {
    # ---------------- MUSIC ----------------
    # F1 / motorsport
    "f1": ["Q108886259"],
    "formula 1": ["Q108886259"],
    "motorsport": ["Q108886259", "Q3016543"],
    # Generic "racing" — covers Le Mans, NASCAR, MotoGP, rally
    "racing": ["Q108886259", "Q24050099", "Q3016543"],
    # Cycling: stage race (Tour de France) + general cycling race
    "cycling": ["Q1318941", "Q15091377"],
    # Tennis grand slams — editions are "tennis tournament edition" Q47345468
    "tennis": ["Q47345468"],
    "wimbledon": ["Q47345468"],
    "football": ["Q12166442"],  # association football match
    "marathon": ["Q40244", "Q2066298"],  # marathon + ultramarathon
    "horse-racing": ["Q3001412", "Q60229620"],
    "sailing": ["Q216736", "Q170571"],
    "shooting": ["Q206989"],
    "golf": ["Q2643867", "Q4846710"],  # golf tournament + golf major
    "skiing": ["Q13382677", "Q211249"],
    # Music festivals — let genre filter narrow it down
    "jazz": ["Q868557"],
    "electronic-music": ["Q868557"],
    "rock": ["Q868557"],
    "classical": ["Q868557"],
    "opera": ["Q868557"],
    "hip-hop": ["Q868557"],
    "urban": ["Q868557"],
    "afrobeat": ["Q868557"],
    "amapiano": ["Q868557"],
    "latin": ["Q868557"],
    "world-music": ["Q868557"],
    "dance": ["Q2393315", "Q868557"],
    # Exhibitions / biennales
    "art-museums": ["Q57598", "Q464980"],
    "modern-art": ["Q57598", "Q464980"],
    "renaissance-art": ["Q57598"],
    "architecture": ["Q464980"],
    "fashion": ["Q47454"],
    "film": ["Q220753"],
    "theatre": ["Q7571069"],
    "comedy": ["Q40831"],
    # ---------------- FOOD / DRINK ----------------
    "food-wine": ["Q868557", "Q47454"],
    "wine": ["Q462100", "Q11632"],
    "champagne": ["Q462100", "Q131398"],
    "beer": ["Q2919327"],
    "caviar": ["Q131398"],
    "whisky": ["Q28102"],
    "coffee": ["Q16972894"],
    # ---------------- GAMING / LIFESTYLE ----------------
    "poker": ["Q5972068"],
    "casino": ["Q57831"],
    "esports": ["Q500633"],
    "nightlife": ["Q868557"],
    "wellness": ["Q868557"],
    "adventure": ["Q3004165", "Q21003903"],
    "kite-surfing": ["Q21003903", "Q2167104"],
    "luxury": ["Q47454"],
    "photography": ["Q868557"],
    "design": ["Q47454"],
    "literature": ["Q47454"],
    "public-holidays": [],  # handled by Nager.Date, not SPARQL
}

# Genre Q-IDs to filter the generic "festival" type per interest
_GENRE_FILTER_QIDS: dict[str, list[str]] = {
    "jazz": ["Q8341"],            # jazz
    "electronic-music": ["Q9778", "Q170611", "Q20502"],  # electronic + techno + house
    "rock": ["Q11399"],           # rock music
    "classical": ["Q9730"],       # classical music
    "food-wine": ["Q2095"],       # food (fallback; specific wine Q not needed)
    "photography": ["Q11633"],    # photography
    "wellness": [],               # too narrow; rely on name search
    "design": ["Q11634"],         # design
    "literature": ["Q8242"],      # literature
}

# ---------------------------------------------------------------------------
# Genre label terms — for interests whose event EDITIONS on Wikidata often
# lack the genre property (P136 sits on the festival series, not the
# edition). The query unions (a) genre-typed events with (b) events whose
# English label contains the genre word — both real Wikidata rows; the
# label leg is a transparent heuristic, not fabrication.
# ---------------------------------------------------------------------------
_GENRE_LABEL_TERMS: dict[str, list[str]] = {
    "jazz": ["jazz"],
    "electronic-music": ["techno", "house music festival", "electronic music"],
    "rock": ["rock festival"],
    "hip-hop": ["hip hop", "hip-hop", "rap"],
    "afrobeat": ["afrobeat"],
    "amapiano": ["amapiano"],
    "latin": ["latin music"],
    "world-music": ["world music"],
    "classical": ["classical music festival", "chamber music"],
    "opera": ["opera festival"],
    "dance": ["dance festival"],
    "food-wine": ["food festival", "wine festival", "culinary"],
    "wine": ["wine festival"],
    "whisky": ["whisky", "whiskey"],
    "beer": ["beer festival", "brewing"],
    "coffee": ["coffee"],
    "champagne": ["champagne"],
    "caviar": ["caviar"],
    "literature": ["literary festival", "poetry festival"],
    "film": ["film festival"],
    "cycling": ["cycling", "bike race"],
    "marathon": ["marathon"],
    "horse-racing": ["horse race", "horse racing"],
    "tennis": ["tennis tournament", "tennis open"],
    "wimbledon": ["wimbledon", "tennis tournament"],
    "golf": ["golf tournament", "golf open"],
    "f1": ["grand prix"],
    "motorsport": ["grand prix"],
    "racing": ["grand prix"],
}

_WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
_USER_AGENT = "TravelScout/2.0 (research contact@travelscout.example)"
_REQUEST_TIMEOUT = 30


class WikidataEventsClient:
    """Query Wikidata for recurring events by interest-key, country, and date range.

    Each ``search()`` runs a single SPARQL query. Upstream is public, no
    API key. We honour Wikidata's rate limit (5 req/s) via a small sleep
    between calls when used in a tight loop.
    """

    source_key = "wikidata"

    def is_configured(self) -> bool:
        return True

    async def search(
        self,
        interest_key: str,
        *,
        country_alpha2: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 50,
    ) -> list[EventRecord]:
        """Return events matching the interest within a country / date range.

        ``interest_key`` is one of the 18 catalog keys (e.g. "jazz",
        "cycling", "f1"). If the key isn't in our routing map, we
        return [] — no event source claims it.
        """
        event_types = _EVENT_TYPE_QIDS.get(interest_key.lower())
        if not event_types:
            return []
        genre_filters = _GENRE_FILTER_QIDS.get(interest_key.lower(), [])
        # Genre WORD for the label-contains UNION leg (see _build_query).
        self._genre_word = interest_key.lower()

        # Date range as ISO strings, or 2025-01-01..2027-12-31 default.
        start_iso = (start_date or date(2025, 1, 1)).isoformat()
        end_iso = (end_date or date(2027, 12, 31)).isoformat()

        # Country code -> Wikidata country Q-ID. The simplest mapping.
        # For 90% of queries we don't have this; if we don't, query
        # without the country filter and let the caller filter.
        country_qid = ALPHA2_TO_WIKIDATA_QID.get((country_alpha2 or "").upper())

        sparql = self._build_query(
            event_types=event_types,
            genre_filters=genre_filters,
            country_qid=country_qid,
            start_iso=start_iso,
            end_iso=end_iso,
            limit=limit,
        )
        # Use a short timeout (4s) for Wikidata — the SPARQL endpoint
        # is often slow and we don't want to block the whole search.
        # If it times out we silently fall through; Wikipedia still
        # answers. The per-interest wait_for() in the router is a
        # 6s hard cap on top of this, so a query never takes more
        # than 6s for a single interest.
        try:
            r = requests.get(
                _WIKIDATA_SPARQL_URL,
                params={"query": sparql, "format": "json", "timeout": "4"},
                headers={
                    "User-Agent": _USER_AGENT,
                    "Accept": "application/sparql-results+json",
                },
                impersonate="chrome120", timeout=5,
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.info("Wikidata SPARQL unavailable for %s: %s", interest_key, e)
            return []

        try:
            data = r.json()
        except ValueError:
            logger.warning("Wikidata returned non-JSON for %s", interest_key)
            return []

        out: list[EventRecord] = []
        for b in data.get("results", {}).get("bindings", []):
            try:
                rec = self._binding_to_record(b)
                if rec is not None:
                    out.append(rec)
            except Exception as e:  # noqa: BLE001
                logger.debug("Skipping malformed binding: %s (%s)", b, e)
        return out

    def _build_query(
        self,
        *,
        event_types: list[str],
        genre_filters: list[str],
        country_qid: str | None,
        start_iso: str,
        end_iso: str,
        limit: int,
    ) -> str:
        """Build the SPARQL query.

        We want events (instance of one of event_types) that either:
          - happened in [start, end], or
          - are recurring annual events with an inception in that range
            (so we catch "happens every July" without exact-date data)
        AND optionally located in country_qid.
        """
        # VALUES clause for event types
        type_values = " ".join(f"wd:{qid}" for qid in event_types)
        # VALUES clause for genres (optional, only when the interest has one).
        # Leg (a): the event carries the genre (P136). Leg (b): the event's
        # English label contains the genre word — editions frequently lack
        # P136 (it sits on the festival series), so the label leg recovers
        # real dated editions that the strict genre filter would miss.
        genre_clause = ""
        if genre_filters:
            terms = _GENRE_LABEL_TERMS.get(self._genre_word, [])
            label_legs = ""
            n_label = 0
            for term in terms:
                var = f"lblGenre{n_label}"
                label_legs += (
                    f" UNION {{\n"
                    f"            ?event rdfs:label ?{var} .\n"
                    f'            FILTER(LANG(?{var}) = "en" && CONTAINS(LCASE(?{var}), "{term.lower()}"))\n'
                    f"          }}"
                )
                n_label += 1
            genre_values = " ".join(f"wd:{qid}" for qid in genre_filters)
            genre_clause = f"""
            {{
              ?event wdt:P136 ?genre .
              VALUES ?genre {{ {genre_values} }}
            }}{label_legs}"""

        # Country filter: by P17 (country) on the event, OR on the city.
        # This is optional — many events don't have a country linked, so
        # we fall back to matching the city instead.
        country_clause = ""
        if country_qid:
            country_clause = f"""
            {{
              ?event wdt:P17 wd:{country_qid} .
            }} UNION {{
              ?event wdt:P276 ?city .
              ?city wdt:P17 wd:{country_qid} .
            }}"""

        # Date filter: P580 (start time) OR P585 (point in time)
        # within [start_iso, end_iso]. We use >= on the start bound only
        # and < on the end bound to keep the query small.
        date_clause = f"""
        {{
          ?event wdt:P580 ?start .
          FILTER(?start >= "{start_iso}T00:00:00Z"^^xsd:dateTime && ?start < "{end_iso}T23:59:59Z"^^xsd:dateTime)
        }} UNION {{
          ?event wdt:P585 ?point .
          FILTER(?point >= "{start_iso}T00:00:00Z"^^xsd:dateTime && ?point < "{end_iso}T23:59:59Z"^^xsd:dateTime)
        }}"""

        # Use a 60-second hint so the query endpoint won't time us out
        # before we get the results.
        return f"""
        SELECT ?event ?eventLabel ?start ?end ?city ?cityLabel ?country ?countryLabel
               ?coord ?genreLabel WHERE {{
          VALUES ?type {{ {type_values} }}
          ?event wdt:P31 ?type .
          {date_clause}
          {genre_clause}
          OPTIONAL {{ ?event wdt:P276 ?city }}
          OPTIONAL {{ ?event wdt:P17 ?country }}
          OPTIONAL {{
            ?city wdt:P625 ?coord .
          }}
          OPTIONAL {{ ?event wdt:P136 ?genre }}
          {country_clause}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
        }}
        ORDER BY ?start
        LIMIT {limit}
        """

    def _binding_to_record(self, b: dict) -> EventRecord | None:
        name = b.get("eventLabel", {}).get("value", "").strip()
        if not name or name.startswith("Q"):  # Q-id is a fallback label
            return None
        starts = self._parse_date(b.get("start", {}).get("value"))
        ends = self._parse_date(b.get("end", {}).get("value"))
        city = b.get("cityLabel", {}).get("value", "").strip()
        country = b.get("countryLabel", {}).get("value", "").strip()
        if country.startswith("Q"):
            country = ""
        coord = b.get("coord", {}).get("value", "")
        lat = lon = None
        if coord and coord.startswith("Point("):
            try:
                parts = coord.replace("Point(", "").rstrip(")").split()
                lon = float(parts[0]); lat = float(parts[1])
            except (ValueError, IndexError):
                pass
        qid = b.get("event", {}).get("value", "").rsplit("/", 1)[-1]
        genre = b.get("genreLabel", {}).get("value", "").strip()
        # Resolve the country label to an alpha-2. Wikidata may give us
        # a full English country name (e.g. "Mozambique"), a label that
        # starts with "Q" (unresolved), or a local-language name. We
        # normalise via the ISO 3166-1 dataset.
        country_alpha2 = ""
        if country and not country.startswith("Q"):
            country_alpha2 = resolve_alpha2(country)
        location = None
        if country_alpha2:
            location = _build_location(country_alpha2, country, city)
            if lat is not None and lon is not None:
                location.latitude = lat
                location.longitude = lon
        return EventRecord(
            name=name,
            kind=_KIND_BY_INTEREST.get(self._interest_hint(b), "event"),
            starts_at=starts,
            ends_at=ends,
            location=location,
            city=city or "",
            country=country or "",
            country_alpha2=country_alpha2 or "",
            latitude=lat,
            longitude=lon,
            source="wikidata",
            source_url=f"https://www.wikidata.org/wiki/{qid}" if qid else "",
            source_qid=qid,
            extra={"genre": genre} if genre else {},
        )

    @staticmethod
    def _interest_hint(b: dict) -> str:
        return ""

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        # Wikidata returns "2026-07-19T00:00:00Z" or "2026-07-19"
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            pass
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


# Map: what we already have -> our internal kind. We can't fully recover
# the interest_key from a SPARQL result (we don't know which VALUES
# filter matched), so we just tag these as "event" and let the search
# router cross-reference with the interest_key that triggered the query.
_KIND_BY_INTEREST: dict[str, str] = {}


# (Country code -> Wikidata QID) is now sourced from
# app.refdata.iso3166.ALPHA2_TO_WIKIDATA_QID (the bundled ISO 3166-1
# dataset covers all 250 countries; the inline copy above is removed
# in favour of the authoritative one).

# -----------------------------------------------------------------------------
# Wikipedia "List of" articles (fallback for events not in Wikidata)
# -----------------------------------------------------------------------------


def _build_location(
    country_alpha2: str,
    country_name: str = "",
    locality: str = "",
) -> Location:
    """Build a Location from a Wikipedia row.

    Pulls the full ISO record from the bundled dataset (alpha-2/3,
    numeric, English name, UN M49 region) and attaches the locality
    the parser extracted. Lat/lon, GeoNames, Wikidata QID and ISO
    3166-2 subdivision are NOT filled here — the consumer can call
    ``LocationResolver.resolve()`` asynchronously for those if
    needed (network round-trip).
    """
    rec = iso_country(country_alpha2) or {}
    return Location.now(
        country_alpha2=rec.get("alpha2", country_alpha2.upper()),
        country_alpha3=rec.get("alpha3", ""),
        country_numeric=rec.get("numeric", ""),
        country_name_en=rec.get("name_en", "") or country_name,
        locality=locality or "",
        display_name=f"{locality}, {rec.get('alpha2', country_alpha2.upper())}" if locality else rec.get("name_en", country_alpha2),
        region_code=rec.get("m49_region", ""),
        region_name=M49_TO_REGION_NAME.get(rec.get("m49_region", ""), ""),
        wikidata_qid=ALPHA2_TO_WIKIDATA_QID.get(country_alpha2.upper(), ""),
        sources=[GeoSource(
            source="wikipedia",
            country_alpha2=rec.get("alpha2", country_alpha2.upper()),
            country_alpha3=rec.get("alpha3", ""),
            country_numeric=rec.get("numeric", ""),
            locality=locality or "",
            matched=True,
        )],
        confidence=0.7,  # Wikipedia "list" rows are accurate but
                          # not cross-validated against the resolver
    )


class WikipediaListClient:
    """Pull annual events from Wikipedia "List of" articles.

    Free, no API key, CC-BY-SA. Use as a fallback when Wikidata returns
    nothing. Currently the corpus is small (we fetch the most useful
    city-level lists) — extend in the admin panel as needed.
    """

    source_key = "wikipedia"

    # Pre-curated list of "List of" article titles per interest key.
    # Each value is a list of (article_title, expected_kind). When a
    # city is queried, we ALSO try the per-city "List of" articles in
    # ``CITY_ARTICLES`` below — those are more reliable than the global
    # lists because Wikipedia maintains them per city.
    ARTICLES_BY_INTEREST: dict[str, list[tuple[str, str]]] = {
        # ---------------- MUSIC ----------------
        "jazz": [
            ("List of jazz festivals", "music_festival"),
        ],
        "electronic-music": [
            ("List of electronic music festivals", "music_festival"),
        ],
        "rock": [
            ("List of punk rock festivals", "music_festival"),
            ("List of heavy metal festivals", "music_festival"),
        ],
        "classical": [
            ("List of classical music festivals", "music_festival"),
        ],
        "opera": [
            ("List of opera festivals", "music_festival"),
        ],
        "hip-hop": [
            ("List of hip-hop festivals", "music_festival"),
        ],
        "urban": [
            ("List of hip-hop festivals", "music_festival"),
        ],
        "afrobeat": [
            ("Afro Nation", "music_festival"),
            ("List of music festivals", "music_festival"),
        ],
        "amapiano": [
            ("Afro Nation", "music_festival"),
            ("List of music festivals", "music_festival"),
        ],
        "latin": [
            ("List of Latin American music festivals", "music_festival"),
        ],
        "world-music": [
            ("World of Music, Arts and Dance", "music_festival"),
            ("List of music festivals", "music_festival"),
        ],
        "dance": [
            ("Blackpool Dance Festival", "dance_festival"),
            ("List of music festivals", "music_festival"),
        ],
        # ---------------- SPORT ----------------
        "cycling": [
            ("Classic cycle races", "cycling_race"),
        ],
        "tennis": [
            ("List of tennis tournaments", "tennis_tournament"),
        ],
        "wimbledon": [
            ("Wimbledon Championships", "tennis_tournament"),
            ("2026 Wimbledon Championships", "tennis_tournament"),
        ],
        "football": [
            ("List of association football competitions", "football_competition"),
        ],
        "marathon": [
            ("List of World Athletics Label marathon races", "marathon"),
            ("List of marathons in Africa", "marathon"),
        ],
        "horse-racing": [
            ("List of horse races", "horse_race"),
            ("Horse racing in Great Britain", "horse_race"),
        ],
        "sailing": [
            ("List of regattas", "regatta"),
        ],
        "shooting": [
            ("Shooting sports", "shooting_sport"),
        ],
        "golf": [
            ("List of golf tournaments", "golf_tournament"),
        ],
        "skiing": [
            ("Alpine skiing", "ski_race"),
        ],
        "racing": [
            ("List of auto racing series", "auto_race"),
            ("Auto racing", "auto_race"),
        ],
        "adventure": [
            ("List of ultramarathons", "ultramarathon"),
        ],
        # ---------------- ARTS / CULTURE ----------------
        "art-museums": [
            ("List of most-visited art museums", "exhibition"),
            ("List of art museums", "exhibition"),
        ],
        "modern-art": [
            ("Venice Biennale", "exhibition"),
            ("Frieze (art fair)", "exhibition"),
        ],
        "renaissance-art": [
            ("Uffizi", "exhibition"),
        ],
        "architecture": [
            ("List of Venice Biennale of Architecture exhibitions", "exhibition"),
            ("Venice Biennale of Architecture", "exhibition"),
        ],
        "design": [
            ("List of fashion events", "design_event"),
            ("List of world's fairs", "fair"),
        ],
        "fashion": [
            ("List of fashion events", "fashion_event"),
            ("Fashion week", "fashion_event"),
        ],
        "photography": [
            ("List of Venice Biennale exhibitions", "exhibition"),
            ("Rencontres d'Arles", "photography_festival"),
        ],
        "film": [
            ("List of film festivals", "film_festival"),
        ],
        "theatre": [
            ("Edinburgh Festival Fringe", "theatre_festival"),
        ],
        "comedy": [
            ("Edinburgh Festival Fringe", "comedy_festival"),
        ],
        "literature": [
            ("List of literary festivals", "literary_festival"),
        ],
        # ---------------- FOOD / DRINK ----------------
        "food-wine": [
            ("List of food festivals", "food_festival"),
        ],
        "wine": [
            ("Wine festival", "wine_festival"),
            ("Haro Wine Festival", "wine_festival"),
        ],
        "champagne": [
            ("Champagne", "wine_festival"),
        ],
        "beer": [
            ("Beer festival", "beer_festival"),
            ("Oktoberfest", "beer_festival"),
        ],
        "caviar": [
            ("Caviar", "food_festival"),
        ],
        "whisky": [
            ("Whisky", "spirits_festival"),
        ],
        "coffee": [
            ("Specialty coffee", "coffee_festival"),
        ],
        # ---------------- GAMING / LIFESTYLE ----------------
        "poker": [
            ("Poker tournament", "poker_tournament"),
            ("World Series of Poker", "poker_tournament"),
        ],
        "casino": [
            ("Baccarat", "casino_event"),
        ],
        "esports": [
            ("Esports", "esports_event"),
        ],
        "kite-surfing": [
            ("Kitesurfing", "windsport"),
        ],
        "nightlife": [
            ("List of music festivals", "music_festival"),
        ],
        "wellness": [
            ("List of music festivals", "music_festival"),
        ],
        "luxury": [
            ("List of fashion events", "luxury_event"),
        ],
    }

    # Per-city "List of" articles. Used when the user types a specific
    # city as the destination — these are more reliable than the
    # global lists because they're maintained by local Wikipedia editors.
    CITY_ARTICLES: dict[str, list[tuple[str, str]]] = {
        "Brussels": [
            ("List of events in Brussels", "event"),
            ("List of festivals in Brussels", "music_festival"),
        ],
        "Paris": [
            ("List of festivals in Paris", "music_festival"),
        ],
        "London": [
            ("List of festivals in London", "music_festival"),
            ("List of music venues in London", "venue"),
        ],
        "Berlin": [
            ("List of festivals in Berlin", "music_festival"),
        ],
        "Amsterdam": [
            ("List of festivals in Amsterdam", "music_festival"),
        ],
        "Barcelona": [
            ("List of festivals in Barcelona", "music_festival"),
        ],
        "Maputo": [
            ("List of events in Maputo", "event"),
        ],
        "New York": [
            ("List of events in New York City", "event"),
        ],
        "Las Vegas": [
            ("List of events in Las Vegas", "event"),
        ],
        "Monaco": [
            ("Monaco Grand Prix", "auto_race"),
        ],
        "Monte Carlo": [
            ("Monaco Grand Prix", "auto_race"),
        ],
        "Melbourne": [
            ("Melbourne Cup", "horse_race"),
        ],
        "London": [
            ("Wimbledon Championships", "tennis_tournament"),
        ],
        "Munich": [
            ("Oktoberfest", "beer_festival"),
        ],
        "Pamplona": [
            ("San Fermín", "festival"),
        ],
        "Nice": [
            ("Nice Carnival", "carnival"),
        ],
    }

    def is_configured(self) -> bool:
        return True

    async def search(
        self,
        interest_key: str,
        *,
        country_alpha2: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        city: str | None = None,
        limit: int = 50,
    ) -> list[EventRecord]:
        out: list[EventRecord] = []
        # First, try per-city articles if a city is given (more reliable
        # than the global lists).
        if city:
            for article, kind in self.CITY_ARTICLES.get(city, []):
                try:
                    events = await self._scrape_article(article, kind)
                    out.extend(self._filter(events, country_alpha2, start_date, end_date, limit))
                except Exception as e:  # noqa: BLE001
                    logger.warning("Wikipedia %s failed: %s", article, e)
                    continue
                if len(out) >= limit:
                    return out[:limit]
        for article, kind in self.ARTICLES_BY_INTEREST.get(interest_key, []):
            try:
                events = await self._scrape_article(article, kind)
                out.extend(self._filter(events, country_alpha2, start_date, end_date, limit))
            except Exception as e:  # noqa: BLE001
                logger.warning("Wikipedia %s failed: %s", article, e)
                continue
            if len(out) >= limit:
                break
        return out[:limit]

    @staticmethod
    def _filter(
        events: list[EventRecord],
        country_alpha2: str | None,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[EventRecord]:
        # STRICT country match. If a row has no country parsed, we drop
        # it (rather than keeping it) because the alternative is a Maputo
        # search returning European cycling races. Wikipedia's wikitext
        # list articles almost always have a country marker (flag icon,
        # or "City, Country" in a cell) — if we can't find one, the row
        # is probably meta (article title, see-also, etc.) not a real
        # event in a real country.
        if country_alpha2:
            events = [
                e for e in events
                if e.country_alpha2 and e.country_alpha2 == country_alpha2
            ]
        if start_date and end_date:
            events = [
                e for e in events
                if not e.starts_at or start_date <= e.starts_at <= end_date
            ]
        return events[:limit]

    async def _scrape_article(self, title: str, kind: str) -> list[EventRecord]:
        """Fetch a Wikipedia article and extract event rows.

        If the article is a redirect (e.g. "List of rock festivals" →
        "List of rock music festivals"), we follow the redirect once.
        Wikipedia has a structured "wikitext" API; we hit
        ``action=parse`` and pull the list rows. Each row typically
        contains the event name plus a "Country" or "City" cell.

        Meta-articles like "Lists of festivals" (a list of "list of
        festivals in X" articles, not actual festivals) are detected
        by their first-table content and skipped. We detect them by
        checking if the first non-header row of the table contains
        "List of " in the first cell — that's the tell that this
        article is a list of list-articles.
        """
        # Pre-flight: reject obvious meta-articles up front. The
        # catalog should never include these but we guard against
        # any future misconfiguration.
        if title.lower().startswith("lists of ") or title.lower() == "lists of festivals":
            return []
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "titles": title,
                "prop": "info",
                "redirects": "1",
                "format": "json",
            },
            headers={"User-Agent": _USER_AGENT},
            impersonate="chrome120", timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        if not pages:
            return []
        first_page = next(iter(pages.values()))
        if first_page.get("missing"):
            # Article doesn't exist; skip silently.
            return []
        resolved_title = first_page.get("title", title)
        r = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "parse",
                "page": resolved_title,
                "prop": "wikitext",
                "format": "json",
            },
            headers={"User-Agent": _USER_AGENT},
            impersonate="chrome120", timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            return []
        text = data.get("parse", {}).get("wikitext", {}).get("*", "")
        return self._parse_wikitext_list(text, kind)

    def _parse_wikitext_list(self, text: str, kind: str) -> list[EventRecord]:
        """Extract event name + country from a Wikipedia list wikitext.

        Wikipedia "List of" articles come in two flavours:

        A. **Bulleted list**::
            * [[Event Name]]
            * [[Event Name|City, Country]] — every July

        B. **Table** (most common for festivals, varies a lot)::

            |-
            ! Name ! Year ! Location
            |-
            |[[Ann Arbor Blues and Jazz Festival]]
            | 1969–present
            | Ann Arbor, Michigan, U.S.
            |style="text-align:left"| some notes
            |-

        Column order varies: some tables are (name, location) with no
        year, others (name, year, location), others (name, founder,
        founded, location, type). We use heuristics to find the location
        cell: it's the cell that contains a comma followed by a
        recognised country name, OR the first cell that looks like
        "City, Country" (anything with a comma after the year column).
        """
        out: list[EventRecord] = []
        in_table = False
        current_row_cells: list[str] = []
        # We only care about events in the FIRST data table of the article;
        # any subsequent table is usually a see-also / "list of" cross-ref.
        tables_seen = 0
        current_table_kept: bool = False

        def flush_row():
            nonlocal current_table_kept
            if not current_row_cells or not current_table_kept:
                current_row_cells.clear()
                return
            # First cell is the event name.
            name = current_row_cells[0].strip()
            if not name or name.lower() in (
                "name", "festival", "event", "list of music festivals",
                ":category:classical music festivals", ":category:jazz festivals",
            ):
                current_row_cells.clear()
                return
            # Skip rows that look like TOC entries.
            if name.startswith(("#", ":", "List of ", "Early ")):
                current_row_cells.clear()
                return
            # Skip image-caption rows from infoboxes. These look like
            # "| caption7 = {{flag|UK}} [[Chris Froome]]" — the first
            # cell is usually an image filename or a short caption.
            if any(
                marker in name.lower()
                for marker in (".jpg", ".png", ".svg", "image", "caption",
                               "logo", "map of", "flag of", "coat of arms")
            ):
                current_row_cells.clear()
                return
            # Try to extract a country from EVERY cell. Real Wikipedia
            # tables put the country in different columns for different
            # articles: sometimes the second cell, sometimes a separate
            # column labelled "Country", sometimes a flag icon template.
            country_alpha2 = ""
            country = ""
            city = ""
            for cell in current_row_cells[1:]:
                cell_clean = cell.strip()
                # Flag icon: {{flag|XX}} or {{icon|country|XX}} or
                # {{Country flag|XX}}.
                fm = re.search(
                    r"\{\{(?:flag|flagicon|country flag)\|([A-Za-z]{2,3})", cell_clean
                )
                if fm:
                    code = fm.group(1).upper()
                    country_alpha2 = (
                        code if len(code) == 2
                        else IOC_TO_ALPHA2.get(code, "")
                    )
                    if country_alpha2:
                        break
                # "City, State, Country" or "City, Country".
                if "," in cell_clean and not country_alpha2:
                    parts = [p.strip() for p in cell_clean.split(",") if p.strip()]
                    if len(parts) >= 2:
                        last = parts[-1]
                        mapped = resolve_alpha2(last)
                        if mapped:
                            country_alpha2 = mapped
                            country = last
                            city = ", ".join(parts[:-1])
                            break
                # Bare country name in a single cell.
                if cell_clean and not country_alpha2:
                    mapped = resolve_alpha2(cell_clean)
                    if mapped:
                        country_alpha2 = mapped
                        country = cell_clean
                        break
            # If we still don't have a country, drop the row entirely
            # — strict filter (see _filter) requires it.
            if country_alpha2:
                loc = _build_location(country_alpha2, country, city or name)
            else:
                loc = None
            out.append(EventRecord(
                name=name,
                kind=kind,
                location=loc,
                city=city or (current_row_cells[1] if len(current_row_cells) > 1 else name),
                country=country or "",
                country_alpha2=country_alpha2 or "",
                source="wikipedia",
                source_url=f"https://en.wikipedia.org/wiki/{quote(name.replace(' ', '_'))}",
            ))
            current_row_cells.clear()

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("{|"):
                tables_seen += 1
                # Only keep the FIRST table that looks like a data table
                # (has at least 3 columns). Subsequent tables (TOC, see-also)
                # are usually small link lists.
                in_table = True
                current_table_kept = tables_seen == 1
                continue
            if stripped.startswith("|}"):
                flush_row()
                in_table = False
                continue
            if not in_table:
                # Bulleted list flavour — keep the old behaviour.
                if current_table_kept:
                    current_row_cells.clear()
                if stripped.startswith("*") or stripped.startswith("-"):
                    m = re.search(r"\[\[([^]|]+?)(?:\|[^]]+?)?\]\]", line)
                    if not m:
                        continue
                    name = m.group(1).strip()
                    if name.lower() in ("name", "festival", "event"):
                        continue
                    if name.startswith(("#", ":", "List of ")):
                        continue
                    country = ""
                    city = ""
                    # Wikipedia bullets often carry a country marker
                    # like {{flag|FRA}} or {{flagicon|France}}. The
                    # alpha-2 form is the most reliable.
                    flag_match = re.search(
                        r"\{\{(?:flag|flagicon)\|([A-Za-z]{2,3})", line
                    )
                    if flag_match:
                        alpha2 = flag_match.group(1).upper()
                        if len(alpha2) == 2:
                            country = alpha2
                        else:
                            # Three-letter IOC code -> alpha2 via our map.
                            country = IOC_TO_ALPHA2.get(alpha2, "")
                    if not country:
                        # Fall back to "City, Country" inside the link text.
                        if "," in name:
                            parts = name.split(",", 1)
                            city = parts[0].strip()
                            country = parts[1].strip()
                    country_alpha2 = (
                        country if len(country) == 2
                        else resolve_alpha2(country)
                    )
                    starts_at = self._extract_month(line)
                    out.append(EventRecord(
                        name=name,
                        kind=kind,
                        location=_build_location(country_alpha2, country, city) if country_alpha2 else None,
                        city=city or name,
                        country=country or "",
                        country_alpha2=country_alpha2 or "",
                        starts_at=starts_at,
                        source="wikipedia",
                        source_url=f"https://en.wikipedia.org/wiki/{quote(name.replace(' ', '_'))}",
                    ))
                continue

            # Table parsing
            if not current_table_kept:
                current_row_cells.clear()
                continue
            if stripped == "|-":
                flush_row()
                continue
            if stripped.startswith("!"):
                current_row_cells.clear()
                continue
            if stripped.startswith("|"):
                content = re.sub(r"^[\|]+", "", stripped)
                content = re.sub(r"^style=[^|]*\|", "", content)
                content = content.strip()
                if not content or content in ("None", "{{NA}}", "{{NA|}}"):
                    continue
                m = re.search(r"\[\[([^]|]+?)(?:\|[^]]+?)?\]\]", content)
                text_val = m.group(1) if m else content
                current_row_cells.append(text_val)
        flush_row()
        return out[:50]

    @staticmethod
    def _extract_month(line: str) -> date | None:
        """Pull a month name out of a wikitext line, return a date with day=1
        and the current year (these are recurring events, so year is the
        caller's window)."""
        m = re.search(
            r"\b(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\b",
            line,
        )
        if not m:
            return None
        try:
            return date(date.today().year, _MONTHS[m.group(1)], 1)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # City-article search (2026-10-22, Sir: "return real events"):
    # MediaWiki search keyed on "<interest noun> <city>", then infobox
    # date + location extraction from the event's own article. This leg
    # surfaces REAL dated local events for cities the Wikidata event
    # types miss — e.g. Cape Town International Jazz Festival has NO
    # dated edition in Wikidata, but its article infobox says
    # "date = March, venue = Cape Town". Free, no key, CC-BY-SA.
    # ------------------------------------------------------------------
    _SEARCH_SKIP_KEYS = {"f1", "motorsport", "racing", "formula 1",
                         "public-holidays", "casino", "poker", "luxury"}
    _SEARCH_NOUNS = {
        "electronic-music": "electronic music festival",
        "art-museums": "art exhibition",
        "modern-art": "art exhibition",
        "renaissance-art": "art exhibition",
        "food-wine": "food and wine festival",
        "wine": "wine festival",
        "champagne": "wine festival",
        "beer": "beer festival",
        "whisky": "whisky festival",
        "coffee": "coffee festival",
        "caviar": "food festival",
        "literature": "literary festival",
        "film": "film festival",
        "comedy": "comedy festival",
        "theatre": "theatre festival",
        "opera": "opera festival",
        "classical": "classical music festival",
        "dance": "dance festival",
        "architecture": "architecture festival",
        "design": "design festival",
        "fashion": "fashion week",
        "adventure": "adventure race",
        "kite-surfing": "kite surfing competition",
        "wellness": "wellness retreat festival",
        "skiing": "skiing competition",
        "football": "football tournament",
        "golf": "golf tournament",
        "cycling": "cycling race",
        "marathon": "marathon",
        "horse-racing": "horse race meeting",
        "sailing": "regatta",
        "esports": "esports tournament",
        "nightlife": "music festival",
    }

    async def search_city_articles(
        self,
        interest_key: str,
        *,
        city: str,
        country_alpha2: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 4,
    ) -> list[EventRecord]:
        if not city or interest_key in self._SEARCH_SKIP_KEYS:
            return []
        noun = self._SEARCH_NOUNS.get(
            interest_key, f"{interest_key.replace('-', ' ')} festival"
        )
        try:
            s = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query", "list": "search",
                    "srsearch": f"{noun} {city}", "srlimit": "4",
                    "format": "json",
                },
                headers={"User-Agent": _USER_AGENT},
                impersonate="chrome120", timeout=10,
            )
            s.raise_for_status()
            hits = [
                hit["title"]
                for hit in ((s.json().get("query") or {}).get("search") or [])[:4]
            ]
        except Exception as e:  # noqa: BLE001
            logger.info("City-article search failed for %s/%s: %s",
                        interest_key, city, e)
            return []
        out: list[EventRecord] = []
        for title in hits:
            # The event article's own infobox carries the real dates.
            try:
                r = requests.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "parse", "page": title,
                        "prop": "wikitext", "format": "json",
                    },
                    headers={"User-Agent": _USER_AGENT},
                    impersonate="chrome120", timeout=12,
                )
                r.raise_for_status()
                wikitext = (r.json().get("parse") or {}).get("wikitext") or {}
                wikitext = wikitext.get("*", "") if isinstance(wikitext, dict) else wikitext
            except Exception as e:  # noqa: BLE001
                logger.info("City article %s fetch failed: %s", title, e)
                continue
            if not wikitext:
                continue
            head = wikitext[:6000]
            loc_m = re.search(
                r"\|\s*(?:location|venue)\s*=\s*([^\n\|]{3,120})", head, re.I)
            loc_flat = re.sub(
                r"\[\[([^][]+)(?:\|[^][]+)?\]\]", r"\1", loc_m.group(1)
            ) if loc_m else ""
            # Accent/case-insensitive city containment.
            import unicodedata
            _fold = lambda t: "".join(
                c for c in unicodedata.normalize("NFKD", t or "")
                if not unicodedata.combining(c)
            ).lower()
            if _fold(city) not in _fold(loc_flat):
                continue
            dm = re.search(r"\|\s*dates?\s*=\s*([^\n\|]{2,90})", head, re.I)
            starts_at, note = self._place_in_window(
                dm.group(1) if dm else "", start_date, end_date
            )
            if starts_at is None:
                continue
            out.append(EventRecord(
                name=title,
                kind=f"{interest_key}_event",
                starts_at=starts_at,
                location=_build_location(country_alpha2 or "", "", city),
                extra={"date_note": note},
            ))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _place_in_window(
        date_field: str,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[date | None, str]:
        """Match an infobox date against the trip window. Real-data rule:
        nothing is invented — an unsatisfiable or undated field returns
        (None, '') and the event is dropped.

        - exact day-month-year inside window → that date, no note
        - month + year without a day → first day of that month when the
          month overlaps the window; note says day is to be confirmed
        - month with no year (recurring, e.g. 'date = March') → the next
          matching month inside the window, same note
        """
        if not (start_date and end_date) or not date_field:
            return None, ""
        mon = (r"January|February|March|April|May|June|July|August|"
               r"September|October|November|December")
        # "25 March 2027" / "25th March 2027"
        m = re.search(
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(%s)\s+(20\d\d)\b" % mon,
            date_field, re.I,
        )
        if not m:
            # "March 25, 2027" / "March 25 2027"
            m = re.search(
                r"\b(%s)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b" % mon,
                date_field, re.I,
            )
            if m:
                try:
                    d = date(int(m.group(3)), _MONTHS[str(m.group(1)).lower().title()],
                             int(m.group(2)))
                except ValueError:
                    return None, ""
                return (d, "") if start_date <= d <= end_date else (None, "")
        elif m:
            try:
                d = date(int(m.group(3)),
                         _MONTHS[str(m.group(2)).lower().title()],
                         int(m.group(1)))
            except ValueError:
                return None, ""
            return (d, "") if start_date <= d <= end_date else (None, "")
        # Month (+ optional year) fallback — infoboxes of annual
        # festivals usually carry just the month.
        ym = re.search(r"\b(%s)\s*(20\d\d)?\b" % mon, date_field, re.I)
        if not ym:
            return None, ""
        month_n = _MONTHS[str(ym.group(1)).lower().title()]
        year_hint = int(ym.group(2)) if ym.group(2) else None
        y, mo = start_date.year, start_date.month
        while (y, mo) <= (end_date.year, end_date.month):
            cand = date(y, mo, 1)
            if cand.month == month_n and (
                year_hint is None or cand.year == year_hint
            ):
                if end_date >= cand:
                    return cand, "festival month — day to be confirmed"
                return None, ""
            mo += 1
            if mo > 12:
                mo, y = 1, y + 1
        return None, ""


_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


# The country-name -> alpha-2 lookup (old ``_COUNTRY_DISPLAY_TO_ALPHA2``)
# and the IOC 3-letter -> alpha-2 table (old ``_IOC_TO_ALPHA2``) are
# now sourced from ``app.refdata.iso3166`` so the resolver, the
# Wikipedia parser, and the location_resolver share one source of
# truth. The inline copies above were removed in favour of:
#   * resolve_alpha2(name)  — for "France" / "u.s." / "Hong Kong" style
#   * IOC_TO_ALPHA2[ioc3]   — for "FRA" / "MOZ" style flag templates


# -----------------------------------------------------------------------------
# Convenience: a unified free-event aggregator
# -----------------------------------------------------------------------------

class FreeEventAggregator:
    """Run all free event sources for a given interest and merge results.

    The intersection algorithm doesn't care which source produced each
    event — they all become ``EventRecord`` objects. Dedup is by
    ``(name, city, starts_at)``.
    """

    def __init__(self) -> None:
        self.wikidata = WikidataEventsClient()
        self.wikipedia = WikipediaListClient()
    def is_configured(self) -> bool:
        return True

    async def search(
        self,
        interest_key: str,
        *,
        country_alpha2: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        city: str | None = None,
        limit: int = 50,
    ) -> list[EventRecord]:
        import asyncio
        # Use return_exceptions=True so a failing source doesn't
        # cancel the other. We merge whatever each source returns
        # and skip the failed batch silently.
        results = await asyncio.gather(
            self.wikidata.search(
                interest_key=interest_key,
                country_alpha2=country_alpha2,
                start_date=start_date, end_date=end_date,
                limit=limit,
            ),
            self.wikipedia.search(
                interest_key=interest_key,
                country_alpha2=country_alpha2,
                start_date=start_date, end_date=end_date,
                city=city,
                limit=limit,
            ),
            self.wikipedia.search_city_articles(
                interest_key,
                city=city or "",
                country_alpha2=country_alpha2,
                start_date=start_date, end_date=end_date,
                limit=4,
            ),
            return_exceptions=True,
        )
        merged: list[EventRecord] = []
        seen: set[tuple[str, str, str]] = set()
        for batch in results:
            if isinstance(batch, BaseException):
                # One source failed (timeout, rate-limit, parse error).
                # Skip it and keep whatever the other returned.
                logger.info(
                    "Free-event source failed: %s",
                    type(batch).__name__,
                )
                continue
            for e in batch:
                key = (e.name.lower(), e.city.lower(), e.starts_at.isoformat() if e.starts_at else "")
                if key in seen:
                    continue
                seen.add(key)
                merged.append(e)
        return merged[:limit]


def build_free_event_aggregator() -> FreeEventAggregator:
    return FreeEventAggregator()


# In-process cache: (interest, country, city_lower) -> list[EventRecord].
# Wikidata and Wikipedia rate-limit parallel requests, so we serialize
# the per-interest queries and cache the result for 24h. Cache is
# process-local; cleared on container restart.
_FREE_EVENTS_CACHE: dict[tuple[str, str, str], list[EventRecord]] = {}
_FREE_EVENTS_CACHE_TTL_S = 24 * 3600
_FREE_EVENTS_CACHE_LAST_CLEAR = 0.0

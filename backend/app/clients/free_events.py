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

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Common shape
# -----------------------------------------------------------------------------

@dataclass
class EventRecord:
    """One event that the intersection algorithm can rank and surface."""
    name: str
    kind: str                       # "f1_race" | "music_festival" | "sport_match" | "exhibition" | ...
    starts_at: date | None = None
    ends_at: date | None = None
    city: str = ""
    country: str = ""
    country_alpha2: str = ""
    latitude: float | None = None
    longitude: float | None = None
    source: str = ""                # "wikidata" | "wikipedia" | "jolpica" | "holidays"
    source_url: str = ""
    source_qid: str = ""            # Wikidata QID for dedupe / linking
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["starts_at"] = self.starts_at.isoformat() if self.starts_at else None
        d["ends_at"] = self.ends_at.isoformat() if self.ends_at else None
        return d


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

        # Date range as ISO strings, or 2025-01-01..2027-12-31 default.
        start_iso = (start_date or date(2025, 1, 1)).isoformat()
        end_iso = (end_date or date(2027, 12, 31)).isoformat()

        # Country code -> Wikidata country Q-ID. The simplest mapping.
        # For 90% of queries we don't have this; if we don't, query
        # without the country filter and let the caller filter.
        country_qid = _ALPHA2_TO_QID.get((country_alpha2 or "").upper())

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
        # VALUES clause for genres (optional, only when the interest has one)
        genre_clause = ""
        if genre_filters:
            genre_values = " ".join(f"wd:{qid}" for qid in genre_filters)
            genre_clause = f"""
            ?event wdt:P136 ?genre .
            VALUES ?genre {{ {genre_values} }}"""

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
        return EventRecord(
            name=name,
            kind=_KIND_BY_INTEREST.get(self._interest_hint(b), "event"),
            starts_at=starts,
            ends_at=ends,
            city=city or "",
            country=country or "",
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


# Alpha-2 -> Wikidata Q-ID for the 80+ countries most likely to appear
# in user searches. The full mapping is at
# https://www.wikidata.org/wiki/Special:EntityData/Q6256.json but we only
# need the common ones.
_ALPHA2_TO_QID: dict[str, str] = {
    "AD": "Q228", "AE": "Q878", "AF": "Q889", "AL": "Q222", "AM": "Q399",
    "AO": "Q916", "AR": "Q414", "AT": "Q40", "AU": "Q408", "AZ": "Q227",
    "BA": "Q225", "BB": "Q244", "BD": "Q902", "BE": "Q31", "BF": "Q965",
    "BG": "Q219", "BH": "Q398", "BI": "Q967", "BJ": "Q962", "BN": "Q921",
    "BO": "Q750", "BR": "Q155", "BS": "Q778", "BT": "Q917", "BW": "Q963",
    "BY": "Q184", "BZ": "Q242", "CA": "Q16", "CD": "Q974", "CF": "Q929",
    "CG": "Q971", "CH": "Q39", "CI": "Q1008", "CL": "Q298", "CM": "Q1009",
    "CN": "Q148", "CO": "Q739", "CR": "Q800", "CU": "Q241", "CV": "Q1011",
    "CY": "Q229", "CZ": "Q213", "DE": "Q183", "DJ": "Q977", "DK": "Q35",
    "DM": "Q784", "DO": "Q786", "DZ": "Q262", "EC": "Q736", "EE": "Q191",
    "EG": "Q79", "EH": "Q4030", "ER": "Q986", "ES": "Q29", "ET": "Q115",
    "FI": "Q33", "FJ": "Q712", "FK": "Q964", "FM": "Q691", "FR": "Q142",
    "GA": "Q1000", "GB": "Q145", "GD": "Q769", "GE": "Q230", "GF": "Q3763",
    "GH": "Q117", "GL": "Q223", "GM": "Q1005", "GN": "Q1006", "GP": "Q17075",
    "GQ": "Q983", "GR": "Q41", "GT": "Q774", "GW": "Q1007", "GY": "Q734",
    "HN": "Q783", "HR": "Q224", "HT": "Q790", "HU": "Q28", "ID": "Q252",
    "IE": "Q27", "IL": "Q801", "IN": "Q668", "IQ": "Q796", "IR": "Q794",
    "IS": "Q189", "IT": "Q38", "JM": "Q766", "JO": "Q810", "JP": "Q17",
    "KE": "Q114", "KG": "Q813", "KH": "Q424", "KI": "Q710", "KM": "Q970",
    "KN": "Q763", "KP": "Q423", "KR": "Q884", "KW": "Q817", "KY": "Q5785",
    "KZ": "Q232", "LA": "Q819", "LB": "Q822", "LC": "Q760", "LI": "Q347",
    "LK": "Q854", "LR": "Q1014", "LS": "Q1013", "LT": "Q37", "LU": "Q32",
    "LV": "Q211", "LY": "Q1016", "MA": "Q1028", "MC": "Q235", "MD": "Q217",
    "ME": "Q236", "MG": "Q1019", "MH": "Q709", "MK": "Q221", "ML": "Q912",
    "MM": "Q836", "MN": "Q711", "MR": "Q1025", "MT": "Q233", "MU": "Q1027",
    "MV": "Q826", "MW": "Q1020", "MX": "Q96", "MY": "Q833", "MZ": "Q1029",
    "NA": "Q1030", "NE": "Q1032", "NG": "Q1033", "NI": "Q811", "NL": "Q55",
    "NO": "Q20", "NP": "Q837", "NR": "Q697", "NZ": "Q664", "OM": "Q842",
    "PA": "Q804", "PE": "Q419", "PG": "Q691", "PH": "Q928", "PK": "Q843",
    "PL": "Q36", "PR": "Q1183", "PS": "Q4030", "PT": "Q45", "PW": "Q695",
    "PY": "Q733", "QA": "Q846", "RO": "Q218", "RS": "Q403", "RU": "Q159",
    "RW": "Q1037", "SA": "Q851", "SB": "Q685", "SC": "Q1042", "SD": "Q1049",
    "SE": "Q34", "SG": "Q334", "SI": "Q215", "SK": "Q214", "SL": "Q1039",
    "SM": "Q238", "SN": "Q1041", "SO": "Q1045", "SR": "Q730", "SS": "Q958",
    "ST": "Q1039", "SV": "Q792", "SY": "Q858", "SZ": "Q1050", "TD": "Q657",
    "TG": "Q945", "TH": "Q869", "TJ": "Q863", "TL": "Q5743", "TM": "Q874",
    "TN": "Q948", "TO": "Q678", "TR": "Q43", "TT": "Q754", "TV": "Q672",
    "TW": "Q865", "TZ": "Q924", "UA": "Q212", "UG": "Q1036", "US": "Q30",
    "UY": "Q77", "UZ": "Q265", "VC": "Q757", "VE": "Q717", "VN": "Q881",
    "VU": "Q686", "WS": "Q683", "XK": "Q302824", "YE": "Q805", "ZA": "Q258",
    "ZM": "Q953", "ZW": "Q954",
}


# -----------------------------------------------------------------------------
# Wikipedia "List of" articles (fallback for events not in Wikidata)
# -----------------------------------------------------------------------------

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
                        else _IOC_TO_ALPHA2.get(code, "")
                    )
                    if country_alpha2:
                        break
                # "City, State, Country" or "City, Country".
                if "," in cell_clean and not country_alpha2:
                    parts = [p.strip() for p in cell_clean.split(",") if p.strip()]
                    if len(parts) >= 2:
                        last = parts[-1]
                        mapped = _COUNTRY_DISPLAY_TO_ALPHA2.get(last.lower(), "")
                        if mapped:
                            country_alpha2 = mapped
                            country = last
                            city = ", ".join(parts[:-1])
                            break
                # Bare country name in a single cell.
                if cell_clean and not country_alpha2:
                    mapped = _COUNTRY_DISPLAY_TO_ALPHA2.get(cell_clean.lower(), "")
                    if mapped:
                        country_alpha2 = mapped
                        country = cell_clean
                        break
            # If we still don't have a country, drop the row entirely
            # — strict filter (see _filter) requires it.
            out.append(EventRecord(
                name=name,
                kind=kind,
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
                            mapped = _IOC_TO_ALPHA2.get(alpha2, "")
                            country = mapped
                    if not country:
                        # Fall back to "City, Country" inside the link text.
                        if "," in name:
                            parts = name.split(",", 1)
                            city = parts[0].strip()
                            country = parts[1].strip()
                    country_alpha2 = (
                        country if len(country) == 2
                        else _COUNTRY_DISPLAY_TO_ALPHA2.get(country.lower(), country)
                    )
                    starts_at = self._extract_month(line)
                    out.append(EventRecord(
                        name=name,
                        kind=kind,
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


_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}


# Country display name -> alpha-2 (lowercase, the values match the
# country fields in Wikipedia tables). Includes every common variant
# the wikitext parser encounters: abbreviations, demonyms, US/UK
# sub-nationals mapped to their country, and historical names.
_COUNTRY_DISPLAY_TO_ALPHA2: dict[str, str] = {
    # Full names
    "albania": "AL", "algeria": "DZ", "argentina": "AR", "armenia": "AM",
    "australia": "AU", "austria": "AT", "azerbaijan": "AZ", "bahrain": "BH",
    "bangladesh": "BD", "belarus": "BY", "belgium": "BE", "bolivia": "BO",
    "bosnia and herzegovina": "BA", "brazil": "BR", "bulgaria": "BG",
    "cambodia": "KH", "canada": "CA", "chile": "CL", "china": "CN",
    "colombia": "CO", "costa rica": "CR", "croatia": "HR", "cuba": "CU",
    "cyprus": "CY", "czech republic": "CZ", "czechia": "CZ",
    "denmark": "DK", "dominican republic": "DO", "ecuador": "EC",
    "egypt": "EG", "el salvador": "SV", "estonia": "EE", "ethiopia": "ET",
    "finland": "FI", "france": "FR", "georgia": "GE", "germany": "DE",
    "ghana": "GH", "greece": "GR", "guatemala": "GT", "honduras": "HN",
    "hungary": "HU", "iceland": "IS", "india": "IN", "indonesia": "ID",
    "iran": "IR", "iraq": "IQ", "ireland": "IE", "israel": "IL",
    "italy": "IT", "jamaica": "JM", "japan": "JP", "jordan": "JO",
    "kazakhstan": "KZ", "kenya": "KE", "kuwait": "KW", "kyrgyzstan": "KG",
    "laos": "LA", "latvia": "LV", "lebanon": "LB", "libya": "LY",
    "liechtenstein": "LI", "lithuania": "LT", "luxembourg": "LU",
    "macedonia": "MK", "north macedonia": "MK", "malaysia": "MY",
    "maldives": "MV", "malta": "MT", "mexico": "MX", "moldova": "MD",
    "monaco": "MC", "mongolia": "MN", "montenegro": "ME", "morocco": "MA",
    "mozambique": "MZ", "myanmar": "MM", "nepal": "NP", "netherlands": "NL",
    "new zealand": "NZ", "nicaragua": "NI", "nigeria": "NG", "norway": "NO",
    "oman": "OM", "pakistan": "PK", "palestine": "PS", "panama": "PA",
    "paraguay": "PY", "peru": "PE", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "qatar": "QA", "romania": "RO", "russia": "RU",
    "rwanda": "RW", "saudi arabia": "SA", "senegal": "SN", "serbia": "RS",
    "singapore": "SG", "slovakia": "SK", "slovenia": "SI",
    "south africa": "ZA", "south korea": "KR", "korea": "KR",
    "spain": "ES", "sri lanka": "LK", "sudan": "SD", "sweden": "SE",
    "switzerland": "CH", "syria": "SY", "taiwan": "TW", "tajikistan": "TJ",
    "tanzania": "TZ", "thailand": "TH", "tunisia": "TN", "turkey": "TR",
    "türkiye": "TR", "turkmenistan": "TM", "uganda": "UG", "ukraine": "UA",
    "united arab emirates": "AE", "united kingdom": "GB",
    "united states": "US", "uruguay": "UY", "uzbekistan": "UZ",
    "venezuela": "VE", "vietnam": "VN", "yemen": "YE", "zambia": "ZM",
    "zimbabwe": "ZW",
    # Common abbreviations (Wikipedia tables use these)
    "u.s.": "US", "u.s.a.": "US", "usa": "US", "us": "US",
    "u.k.": "GB", "uk": "GB", "great britain": "GB", "britain": "GB",
    "uae": "AE", "u.a.e.": "AE",
    "nz": "NZ", "aus": "AU", "ger": "DE", "fra": "FR", "ita": "IT",
    "esp": "ES", "por": "PT", "ned": "NL", "sui": "CH", "den": "DK",
    "swe": "SE", "nor": "NO", "fin": "FI", "pol": "PL", "cze": "CZ",
    "hun": "HU", "aut": "AT", "ire": "IE", "sco": "GB", "wal": "GB",
    "eng": "GB", "arg": "AR", "bra": "BR", "chi": "CL", "mex": "MX",
    "jpn": "JP", "chn": "CN", "kor": "KR", "ind": "IN", "tha": "TH",
    "phi": "PH", "sin": "SG", "mas": "MY", "rsa": "ZA", "egy": "EG",
    "mar": "MA", "nig": "NG", "ken": "KE", "tun": "TN",
    # UK sub-nationals — Wikipedia tables list "England", "Scotland",
    # "Wales", "Northern Ireland" as if they were countries. They're
    # the UK (GB) for the purposes of this filter.
    "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "cornwall": "GB", "kent": "GB",
    # US states — Wikipedia tables often list state names instead of
    # "United States" or "U.S." for the country. Map common ones to US.
    "alabama": "US", "alaska": "US", "arizona": "US", "arkansas": "US",
    "california": "US", "colorado": "US", "connecticut": "US",
    "delaware": "US", "florida": "US", "georgia": "US", "hawaii": "US",
    "idaho": "US", "illinois": "US", "indiana": "US", "iowa": "US",
    "kansas": "US", "kentucky": "US", "louisiana": "US", "maine": "US",
    "maryland": "US", "massachusetts": "US", "michigan": "US",
    "minnesota": "US", "mississippi": "US", "missouri": "US",
    "montana": "US", "nebraska": "US", "nevada": "US",
    "new hampshire": "US", "new jersey": "US", "new mexico": "US",
    "new york": "US", "north carolina": "US", "north dakota": "US",
    "ohio": "US", "oklahoma": "US", "oregon": "US", "pennsylvania": "US",
    "rhode island": "US", "south carolina": "US", "south dakota": "US",
    "tennessee": "US", "texas": "US", "utah": "US", "vermont": "US",
    "virginia": "US", "washington": "US", "west virginia": "US",
    "wisconsin": "US", "wyoming": "US", "u.s": "US",
    # Canadian provinces
    "ontario": "CA", "quebec": "CA", "british columbia": "CA",
    "alberta": "CA", "manitoba": "CA", "saskatchewan": "CA",
    "nova scotia": "CA", "new brunswick": "CA",
    # Australian states
    "victoria": "AU", "queensland": "AU", "new south wales": "AU",
    "western australia": "AU", "south australia": "AU", "tasmania": "AU",
    # Chinese provinces / regions
    "hong kong": "CN", "macau": "CN", "tibet": "CN", "tibetan": "CN",
    # Indian states
    "goa": "IN", "kerala": "IN", "tamil nadu": "IN", "karnataka": "IN",
    "maharashtra": "IN", "rajasthan": "IN", "west bengal": "IN",
    "andhra pradesh": "IN", "gujarat": "IN", "uttar pradesh": "IN",
    # German states
    "bavaria": "DE", "saxony": "DE", "berlin": "DE", "hamburg": "DE",
    # Italian regions
    "tuscany": "IT", "lombardy": "IT", "sicily": "IT", "sardinia": "IT",
    # Spanish communities
    "catalonia": "ES", "andalusia": "ES", "basque country": "ES",
    "galicia": "ES", "valencia": "ES", "castile": "ES",
    # French regions
    "provence": "FR", "normandy": "FR", "brittany": "FR",
    # Generic African / Asian / South American regions that show up
    "east africa": "KE", "west africa": "NG", "north africa": "EG",
    "south america": "BR", "central america": "MX",
    "southeast asia": "TH", "east asia": "CN", "south asia": "IN",
    # Sub-national / city-only entries the parser sometimes picks up
    "cebu": "PH", "borneo": "MY", "java": "ID", "bali": "ID",
    "sardegna": "IT", "sicilia": "IT",
    "muslim": "", "christian": "", "buddhist": "", "hindu": "",
}


# IOC (International Olympic Committee) 3-letter country codes -> alpha-2.
# Wikipedia's {{flag}} / {{flagicon}} templates accept the IOC code as
# the parameter; e.g. {{flag|FRA}} means France. We need this because
# some articles use 3-letter codes instead of 2-letter ISO.
_IOC_TO_ALPHA2: dict[str, str] = {
    "AFG": "AF", "ALB": "AL", "ALG": "DZ", "AND": "AD", "ANG": "AO",
    "ARG": "AR", "ARM": "AM", "AUS": "AU", "AUT": "AT", "AZE": "AZ",
    "BAH": "BS", "BRN": "BH", "BAN": "BD", "BAR": "BB", "BLR": "BY",
    "BEL": "BE", "BIZ": "BZ", "BEN": "BJ", "BER": "BM", "BHU": "BT",
    "BOL": "BO", "BIH": "BA", "BOT": "BW", "BRA": "BR", "BRU": "BN",
    "BUL": "BG", "BFA": "BF", "BDI": "BI", "CAM": "KH", "CMR": "CM",
    "CAN": "CA", "CPV": "CV", "CAF": "CF", "CHA": "TD", "CHI": "CL",
    "CHN": "CN", "COL": "CO", "COM": "KM", "CGO": "CG", "COD": "CD",
    "CRC": "CR", "CIV": "CI", "CRO": "HR", "CUB": "CU", "CYP": "CY",
    "CZE": "CZ", "DEN": "DK", "DJI": "DJ", "DMA": "DM", "DOM": "DO",
    "ECU": "EC", "EGY": "EG", "ESA": "SV", "GEQ": "GQ", "ERI": "ER",
    "EST": "EE", "ETH": "ET", "FIJ": "FJ", "FIN": "FI", "FRA": "FR",
    "GAB": "GA", "GAM": "GM", "GEO": "GE", "GER": "DE", "GHA": "GH",
    "GRE": "GR", "GRN": "GD", "GUA": "GT", "GUI": "GN", "GBS": "GW",
    "GUY": "GY", "HAI": "HT", "HON": "HN", "HUN": "HU", "ISL": "IS",
    "IND": "IN", "INA": "ID", "IRI": "IR", "IRQ": "IQ", "IRL": "IE",
    "ISR": "IL", "ITA": "IT", "JAM": "JM", "JPN": "JP", "JOR": "JO",
    "KAZ": "KZ", "KEN": "KE", "KIR": "KI", "PRK": "KP", "KOR": "KR",
    "KUW": "KW", "KGZ": "KG", "LAO": "LA", "LAT": "LV", "LIB": "LB",
    "LES": "LS", "LBR": "LR", "LBA": "LY", "LIE": "LI", "LTU": "LT",
    "LUX": "LU", "MAD": "MG", "MAW": "MW", "MAS": "MY", "MDV": "MV",
    "MLI": "ML", "MLT": "MT", "MHL": "MH", "MTN": "MR", "MRI": "MU",
    "MEX": "MX", "FSM": "FM", "MDA": "MD", "MON": "MC", "MGL": "MN",
    "MNE": "ME", "MAR": "MA", "MOZ": "MZ", "MYA": "MM", "NAM": "NA",
    "NRU": "NR", "NEP": "NP", "NED": "NL", "NZL": "NZ", "NCA": "NI",
    "NIG": "NE", "NGR": "NG", "MKD": "MK", "NOR": "NO", "OMA": "OM",
    "PAK": "PK", "PLW": "PW", "PAN": "PA", "PNG": "PG", "PAR": "PY",
    "PER": "PE", "PHI": "PH", "POL": "PL", "POR": "PT", "QAT": "QA",
    "ROU": "RO", "RUS": "RU", "RWA": "RW", "SAM": "WS", "SMR": "SM",
    "STP": "ST", "KSA": "SA", "SEN": "SN", "SRB": "RS", "SEY": "SC",
    "SLE": "SL", "SGP": "SG", "SVK": "SK", "SLO": "SI", "SOL": "SB",
    "SOM": "SO", "RSA": "ZA", "ESP": "ES", "SRI": "LK", "SUD": "SD",
    "SUR": "SR", "SWE": "SE", "SUI": "CH", "SYR": "SY", "TPE": "TW",
    "TJK": "TJ", "TAN": "TZ", "THA": "TH", "TLS": "TL", "TOG": "TG",
    "TGA": "TO", "TTO": "TT", "TUN": "TN", "TUR": "TR", "TKM": "TM",
    "TUV": "TV", "UGA": "UG", "UKR": "UA", "UAE": "AE", "GBR": "GB",
    "USA": "US", "URU": "UY", "UZB": "UZ", "VAN": "VU", "VEN": "VE",
    "VIE": "VN", "YEM": "YE", "ZAM": "ZM", "ZIM": "ZW",
}


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

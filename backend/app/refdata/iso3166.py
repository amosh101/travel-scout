"""ISO 3166-1 + M49 + IOC + ISO 4217 (currency) reference data.

Loaded from ``app/data/iso3166.json`` (fetched from the mledoze/countries
public dataset, which mirrors the official ISO 3166-1 list and adds
UN M49 region codes).

We keep two indexes for O(1) lookup:
  - by alpha-2: ``_BY_A2[a2] -> dict``
  - by alpha-3: ``_BY_A3[a3] -> dict``
  - by numeric: ``_BY_N[n]  -> dict``
  - by English name (lowercased): ``_BY_NAME[name] -> dict``
  - by alpha-2 M49: ``_BY_M49[code] -> [dict]``

And expose:
  - ``resolve_alpha2(s)`` — any form (alpha-2/3, numeric, English,
    local-language, demonym) -> alpha-2
  - ``country(a2)`` — full record by alpha-2
  - ``M49_TO_REGION[code] = name`` — region lookup
  - ``LANG_ALPHA2_TO_EN[lang][local_name] = a2`` — common misspellings
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "iso3166.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    if not _DATA_PATH.exists():
        logger.error("ISO 3166-1 data file missing at %s", _DATA_PATH)
        return {}
    with open(_DATA_PATH) as f:
        raw = json.load(f)
    # Two shapes are accepted: the file is either a flat dict of
    # alpha-2 -> record (the mledoze/mledoze format we ship) or a
    # wrapper dict with a "countries" key. Support both so the
    # schema can evolve without breaking the loader.
    if isinstance(raw, dict) and "countries" in raw and isinstance(raw["countries"], dict):
        countries = raw["countries"]
    else:
        countries = raw
    # Build name/alpha-3/numeric/region/area indexes
    out: dict[str, dict[str, Any]] = {}
    by_a3: dict[str, str] = {}
    by_num: dict[str, str] = {}
    by_name: dict[str, str] = {}
    by_m49: dict[str, list[str]] = {}
    for a2, c in countries.items():
        if not isinstance(c, dict) or a2.startswith("_"):
            continue
        out[a2] = c
        if c.get("alpha3"):
            by_a3[c["alpha3"]] = a2
        if c.get("numeric"):
            by_num[c["numeric"]] = a2
        if c.get("name_en"):
            by_name[c["name_en"].lower()] = a2
        # Add all translations
        for lang, name in (c.get("translations") or {}).items():
            if name and isinstance(name, str):
                by_name.setdefault(name.lower(), a2)
        m49 = c.get("m49_region", "")
        if m49:
            by_m49.setdefault(m49, []).append(a2)
    out["_by_a3"] = {"_": by_a3}  # type: ignore[assignment]
    out["_by_num"] = {"_": by_num}
    out["_by_name"] = {"_": by_name}
    out["_by_m49"] = {"_": by_m49}
    return out  # type: ignore[return-value]


def country(a2: str) -> dict[str, Any] | None:
    """Return the full ISO 3166-1 record for an alpha-2 code (uppercase)."""
    if not a2:
        return None
    return _load().get(a2.upper())


def all_countries() -> list[dict[str, Any]]:
    return [c for k, c in _load().items() if not k.startswith("_")]


# Region code -> name (UN M49)
M49_TO_REGION_NAME: dict[str, str] = {
    "002": "Africa",
    "019": "Americas",
    "142": "Asia",
    "150": "Europe",
    "009": "Oceania",
    "AQ":  "Antarctic",
}


def m49_name(code: str) -> str:
    return M49_TO_REGION_NAME.get(code, "")


# IOC 3-letter -> ISO alpha-2. Bundled inline; full set covers every
# National Olympic Committee recognized by the IOC. Mirrors the
# `_IOC_TO_ALPHA2` table in ``free_events.py`` — kept here for the
# resolver so the lookup doesn't depend on the free_events module.
IOC_TO_ALPHA2: dict[str, str] = {
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


# ISO 3166-1 alpha-2 -> country Wikidata QID. Mirrors the inline map in
# free_events.py but exposed here for the resolver.
ALPHA2_TO_WIKIDATA_QID: dict[str, str] = {
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


# Common country-name aliases / demonyms / historical names that
# aren't in the mledoze translation set. Augments the lookup in
# resolve_alpha2().
_NAME_ALIASES: dict[str, str] = {
    # Demonyms + informal
    "holland": "NL", "the netherlands": "NL", "dutch": "NL",
    "britain": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "u.k.": "GB", "u.k": "GB",
    "america": "US", "u.s.": "US", "u.s": "US", "usa": "US",
    "united states of america": "US",
    "uae": "AE", "u.a.e.": "AE", "emirates": "AE",
    "saudi": "SA", "ksa": "SA",
    "rsa": "ZA",
    "ua": "UA",
    "türkiye": "TR", "turkiye": "TR",
    "czechia": "CZ", "czech republic": "CZ",
    "burma": "MM", "mynamar": "MM",  # common misspellings
    "ivory coast": "CI", "cote d'ivoire": "CI", "côte d'ivoire": "CI",
    "swaziland": "SZ", "eswatini": "SZ",
    "east timor": "TL", "timor-leste": "TL",
    "macedonia": "MK", "fyrom": "MK",
    "korea": "KR", "south korea": "KR", "north korea": "KP",
    "vatican": "VA", "holy see": "VA",
    "palestine": "PS", "palestinian territories": "PS",
    "cabo verde": "CV", "cape verde": "CV",
    "congo (brazzaville)": "CG", "congo (kinshasa)": "CD", "drc": "CD",
    "laos": "LA", "lao people's democratic republic": "LA",
    "syria": "SY", "syrian arab republic": "SY",
    "iran": "IR", "persia": "IR",
    "burundi": "BI",
    "kosovo": "XK",
    "byelorussia": "BY", "belorussia": "BY",
    "tibetan": "CN",
    # US states
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
    "wisconsin": "US", "wyoming": "US",
    # Canadian provinces
    "ontario": "CA", "quebec": "CA", "british columbia": "CA",
    "alberta": "CA", "manitoba": "CA", "saskatchewan": "CA",
    "nova scotia": "CA", "new brunswick": "CA",
    # Australian states
    "victoria": "AU", "queensland": "AU", "new south wales": "AU",
    "western australia": "AU", "south australia": "AU", "tasmania": "AU",
    # Chinese provinces / regions
    "hong kong": "CN", "macau": "CN", "macao": "CN", "tibet": "CN",
    # Indian states
    "goa": "IN", "kerala": "IN", "tamil nadu": "IN", "karnataka": "IN",
    "maharashtra": "IN", "rajasthan": "IN", "west bengal": "IN",
    "andhra pradesh": "IN", "gujarat": "IN", "uttar pradesh": "IN",
    # German states
    "bavaria": "DE", "saxony": "DE", "berlin": "DE", "hamburg": "DE",
    # Italian regions
    "tuscany": "IT", "lombardy": "IT", "sicily": "IT", "sardinia": "IT",
    "sardegna": "IT", "sicilia": "IT",
    # Spanish communities
    "catalonia": "ES", "andalusia": "ES", "basque country": "ES",
    "galicia": "ES", "valencia": "ES", "castile": "ES",
    # French regions
    "provence": "FR", "normandy": "FR", "brittany": "FR",
    # Generic African / Asian / South American regions
    "east africa": "KE", "west africa": "NG", "north africa": "EG",
    "south america": "BR", "central america": "MX",
    "southeast asia": "TH", "east asia": "CN", "south asia": "IN",
    # Sub-national / city-only entries the parser sometimes picks up
    "cebu": "PH", "borneo": "MY", "java": "ID", "bali": "ID",
    "kent": "GB", "cornwall": "GB",
    # Religious / cultural descriptors — used to be in the old map
    # with empty values (intentional non-matches)
    "muslim": "", "christian": "", "buddhist": "", "hindu": "",
}


def resolve_alpha2(s: str) -> str:
    """Best-effort normalisation of any country string -> ISO alpha-2.

    Accepts:
      * alpha-2/alpha-3/3-digit numeric
      * English short name
      * any local-language translation in the mledoze dataset
      * demonyms and historical names via ``_NAME_ALIASES``

    Returns empty string if no match.
    """
    if not s:
        return ""
    s = s.strip()
    # Direct alpha-2
    if len(s) == 2 and s.isalpha():
        rec = _load().get(s.upper())
        if rec:
            return s.upper()
    # Alpha-3
    if len(s) == 3 and s.isalpha():
        idx = _load().get("_by_a3", {}).get("_", {})
        a2 = idx.get(s.upper())
        if a2:
            return a2
        # IOC fallback
        if s.upper() in IOC_TO_ALPHA2:
            return IOC_TO_ALPHA2[s.upper()]
    # 3-digit numeric
    if s.isdigit() and len(s) in (1, 2, 3):
        idx = _load().get("_by_num", {}).get("_", {})
        a2 = idx.get(s.zfill(3))
        if a2:
            return a2
    # Lowercase lookup
    low = s.lower()
    idx = _load().get("_by_name", {}).get("_", {})
    a2 = idx.get(low)
    if a2:
        return a2
    # Alias
    if low in _NAME_ALIASES:
        return _NAME_ALIASES[low]
    # Substring: "City, Country" or "City, CC" at end
    if "," in s:
        suffix = s.rsplit(",", 1)[-1].strip()
        a2 = resolve_alpha2(suffix)
        if a2:
            return a2
    return ""


__all__ = [
    "country",
    "all_countries",
    "M49_TO_REGION_NAME",
    "m49_name",
    "IOC_TO_ALPHA2",
    "ALPHA2_TO_WIKIDATA_QID",
    "resolve_alpha2",
]

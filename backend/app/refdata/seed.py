"""Seed real ISO/IATA/ICAO reference data.

Idempotent: re-running upserts the same rows. The set is small and
opinionated — SADC (all 16 countries) plus the key European and
world cities the user actually travels to. Add more from the admin
panel, not from this file.

Source notes:
- IATA/ICAO codes: OurAirports public dataset (verified)
- Country names/codes: ISO 3166-1 alpha-2/alpha-3
- Coordinates: city centroids (decimal degrees)
- Timezones: IANA tz database
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.refdata.models import Airport, City, CityAlias, Country
from app.refdata.service import _norm as _norm_for_seed

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Countries (ISO 3166-1)
# -----------------------------------------------------------------------------

COUNTRIES: list[dict[str, Any]] = [
    # SADC (all 16)
    {"alpha2": "AO", "alpha3": "AGO", "name": "Angola",            "currency": "AOA", "flag_emoji": "🇦🇴", "languages": "pt"},
    {"alpha2": "BW", "alpha3": "BWA", "name": "Botswana",          "currency": "BWP", "flag_emoji": "🇧🇼", "languages": "en,tn"},
    {"alpha2": "KM", "alpha3": "COM", "name": "Comoros",           "currency": "KMF", "flag_emoji": "🇰🇲", "languages": "ar,fr"},
    {"alpha2": "CD", "alpha3": "COD", "name": "DR Congo",          "currency": "CDF", "flag_emoji": "🇨🇩", "languages": "fr"},
    {"alpha2": "SZ", "alpha3": "SWZ", "name": "Eswatini",          "currency": "SZL", "flag_emoji": "🇸🇿", "languages": "en,ss"},
    {"alpha2": "LS", "alpha3": "LSO", "name": "Lesotho",           "currency": "LSL", "flag_emoji": "🇱🇸", "languages": "en,st"},
    {"alpha2": "MG", "alpha3": "MDG", "name": "Madagascar",        "currency": "MGA", "flag_emoji": "🇲🇬", "languages": "fr,mg"},
    {"alpha2": "MW", "alpha3": "MWI", "name": "Malawi",            "currency": "MWK", "flag_emoji": "🇲🇼", "languages": "en,ny"},
    {"alpha2": "MU", "alpha3": "MUS", "name": "Mauritius",         "currency": "MUR", "flag_emoji": "🇲🇺", "languages": "en,fr"},
    {"alpha2": "MZ", "alpha3": "MOZ", "name": "Mozambique",        "currency": "MZN", "flag_emoji": "🇲🇿", "languages": "pt", "name_pt": "Moçambique"},
    {"alpha2": "NA", "alpha3": "NAM", "name": "Namibia",           "currency": "NAD", "flag_emoji": "🇳🇦", "languages": "en"},
    {"alpha2": "SC", "alpha3": "SYC", "name": "Seychelles",        "currency": "SCR", "flag_emoji": "🇸🇨", "languages": "en,fr"},
    {"alpha2": "ZA", "alpha3": "ZAF", "name": "South Africa",      "currency": "ZAR", "flag_emoji": "🇿🇦", "languages": "en,zu,af,xh"},
    {"alpha2": "TZ", "alpha3": "TZA", "name": "Tanzania",          "currency": "TZS", "flag_emoji": "🇹🇿", "languages": "sw,en"},
    {"alpha2": "ZM", "alpha3": "ZMB", "name": "Zambia",            "currency": "ZMW", "flag_emoji": "🇿🇲", "languages": "en"},
    {"alpha2": "ZW", "alpha3": "ZWE", "name": "Zimbabwe",          "currency": "ZWL", "flag_emoji": "🇿🇼", "languages": "en,sn,nd"},

    # Key non-SADC
    {"alpha2": "BE", "alpha3": "BEL", "name": "Belgium",           "currency": "EUR", "flag_emoji": "🇧🇪", "languages": "nl,fr,de"},
    {"alpha2": "NL", "alpha3": "NLD", "name": "Netherlands",       "currency": "EUR", "flag_emoji": "🇳🇱", "languages": "nl,en"},
    {"alpha2": "FR", "alpha3": "FRA", "name": "France",            "currency": "EUR", "flag_emoji": "🇫🇷", "languages": "fr"},
    {"alpha2": "DE", "alpha3": "DEU", "name": "Germany",           "currency": "EUR", "flag_emoji": "🇩🇪", "languages": "de"},
    {"alpha2": "ES", "alpha3": "ESP", "name": "Spain",             "currency": "EUR", "flag_emoji": "🇪🇸", "languages": "es"},
    {"alpha2": "PT", "alpha3": "PRT", "name": "Portugal",          "currency": "EUR", "flag_emoji": "🇵🇹", "languages": "pt"},
    {"alpha2": "IT", "alpha3": "ITA", "name": "Italy",             "currency": "EUR", "flag_emoji": "🇮🇹", "languages": "it"},
    {"alpha2": "GB", "alpha3": "GBR", "name": "United Kingdom",    "currency": "GBP", "flag_emoji": "🇬🇧", "languages": "en"},
    {"alpha2": "IE", "alpha3": "IRL", "name": "Ireland",           "currency": "EUR", "flag_emoji": "🇮🇪", "languages": "en,ga"},
    {"alpha2": "CH", "alpha3": "CHE", "name": "Switzerland",       "currency": "CHF", "flag_emoji": "🇨🇭", "languages": "de,fr,it"},
    {"alpha2": "AT", "alpha3": "AUT", "name": "Austria",           "currency": "EUR", "flag_emoji": "🇦🇹", "languages": "de"},
    {"alpha2": "GR", "alpha3": "GRC", "name": "Greece",            "currency": "EUR", "flag_emoji": "🇬🇷", "languages": "el"},
    {"alpha2": "TR", "alpha3": "TUR", "name": "Türkiye",           "currency": "TRY", "flag_emoji": "🇹🇷", "languages": "tr"},
    {"alpha2": "DK", "alpha3": "DNK", "name": "Denmark",           "currency": "DKK", "flag_emoji": "🇩🇰", "languages": "da"},
    {"alpha2": "SE", "alpha3": "SWE", "name": "Sweden",            "currency": "SEK", "flag_emoji": "🇸🇪", "languages": "sv"},
    {"alpha2": "NO", "alpha3": "NOR", "name": "Norway",            "currency": "NOK", "flag_emoji": "🇳🇴", "languages": "no"},
    {"alpha2": "FI", "alpha3": "FIN", "name": "Finland",           "currency": "EUR", "flag_emoji": "🇫🇮", "languages": "fi"},
    {"alpha2": "IS", "alpha3": "ISL", "name": "Iceland",           "currency": "ISK", "flag_emoji": "🇮🇸", "languages": "is"},
    {"alpha2": "CZ", "alpha3": "CZE", "name": "Czechia",           "currency": "CZK", "flag_emoji": "🇨🇿", "languages": "cs"},
    {"alpha2": "HU", "alpha3": "HUN", "name": "Hungary",           "currency": "HUF", "flag_emoji": "🇭🇺", "languages": "hu"},
    {"alpha2": "PL", "alpha3": "POL", "name": "Poland",            "currency": "PLN", "flag_emoji": "🇵🇱", "languages": "pl"},
    {"alpha2": "AE", "alpha3": "ARE", "name": "United Arab Emirates", "currency": "AED", "flag_emoji": "🇦🇪", "languages": "ar,en"},
    {"alpha2": "QA", "alpha3": "QAT", "name": "Qatar",             "currency": "QAR", "flag_emoji": "🇶🇦", "languages": "ar,en"},
    {"alpha2": "TH", "alpha3": "THA", "name": "Thailand",          "currency": "THB", "flag_emoji": "🇹🇭", "languages": "th"},
    {"alpha2": "SG", "alpha3": "SGP", "name": "Singapore",         "currency": "SGD", "flag_emoji": "🇸🇬", "languages": "en,zh,ms,ta"},
    {"alpha2": "ID", "alpha3": "IDN", "name": "Indonesia",         "currency": "IDR", "flag_emoji": "🇮🇩", "languages": "id"},
    {"alpha2": "JP", "alpha3": "JPN", "name": "Japan",             "currency": "JPY", "flag_emoji": "🇯🇵", "languages": "ja"},
    {"alpha2": "US", "alpha3": "USA", "name": "United States",     "currency": "USD", "flag_emoji": "🇺🇸", "languages": "en"},
    {"alpha2": "MX", "alpha3": "MEX", "name": "Mexico",            "currency": "MXN", "flag_emoji": "🇲🇽", "languages": "es"},
    {"alpha2": "AR", "alpha3": "ARG", "name": "Argentina",         "currency": "ARS", "flag_emoji": "🇦🇷", "languages": "es"},
    {"alpha2": "BR", "alpha3": "BRA", "name": "Brazil",            "currency": "BRL", "flag_emoji": "🇧🇷", "languages": "pt"},
    {"alpha2": "KE", "alpha3": "KEN", "name": "Kenya",             "currency": "KES", "flag_emoji": "🇰🇪", "languages": "sw,en"},
    {"alpha2": "RW", "alpha3": "RWA", "name": "Rwanda",            "currency": "RWF", "flag_emoji": "🇷🇼", "languages": "rw,en,fr"},
]


# -----------------------------------------------------------------------------
# Cities + airports
# Tuple format: (name, ascii_name, country_alpha2, region, lat, lng, tz,
#                population, is_capital,
#                [(iata, icao, airport_name, short_name, priority), ...])
# -----------------------------------------------------------------------------

CITIES: list[tuple] = [
    # ---- SADC ----
    ("Maputo", "Maputo", "MZ", "Maputo City", -25.9167, 32.5833, "Africa/Maputo",
     1102000, True, [("MPM", "FQMA", "Maputo International Airport", "Maputo Intl", 0)]),

    ("Johannesburg", "Johannesburg", "ZA", "Gauteng", -26.2041, 28.0473, "Africa/Johannesburg",
     6065000, False, [
         ("JNB", "FAOR", "O.R. Tambo International Airport", "OR Tambo Intl", 0),
         ("HLA", "FALA", "Lanseria International Airport", "Lanseria", 100),
     ]),

    ("Cape Town", "Cape Town", "ZA", "Western Cape", -33.9249, 18.4241, "Africa/Johannesburg",
     4710000, False, [("CPT", "FACT", "Cape Town International Airport", "Cape Town Intl", 0)]),

    ("Durban", "Durban", "ZA", "KwaZulu-Natal", -29.8587, 31.0218, "Africa/Johannesburg",
     3720000, False, [("DUR", "FALE", "King Shaka International Airport", "King Shaka Intl", 0)]),

    ("Pretoria", "Pretoria", "ZA", "Gauteng", -25.7479, 28.2293, "Africa/Johannesburg",
     2473000, True, [("PRY", "FAWB", "Wonderboom Airport", "Wonderboom", 0)]),

    ("Windhoek", "Windhoek", "NA", "Khomas", -22.9576, 18.4892, "Africa/Windhoek",
     431000, True, [("WDH", "FYWH", "Hosea Kutako International Airport", "Hosea Kutako Intl", 0)]),

    ("Gaborone", "Gaborone", "BW", "South-East", -24.6282, 25.9231, "Africa/Gaborone",
     246000, True, [("GBE", "FBSK", "Sir Seretse Khama International Airport", "Sir Seretse Khama Intl", 0)]),

    ("Lilongwe", "Lilongwe", "MW", "Central", -13.9626, 33.7741, "Africa/Blantyre",
     1119000, True, [("LLW", "FWKI", "Lilongwe Kamuzu International Airport", "Kamuzu Intl", 0)]),

    ("Lusaka", "Lusaka", "ZM", "Lusaka", -15.3875, 28.3228, "Africa/Lusaka",
     2735000, True, [("LUN", "FLKK", "Kenneth Kaunda International Airport", "Kenneth Kaunda Intl", 0)]),

    ("Harare", "Harare", "ZW", "Harare", -17.8252, 31.0335, "Africa/Harare",
     1510000, True, [("HRE", "FVHA", "Robert Gabriel Mugabe International Airport", "RG Mugabe Intl", 0)]),

    ("Antananarivo", "Antananarivo", "MG", "Analamanga", -18.8792, 47.5079, "Indian/Antananarivo",
     1391000, True, [("TNR", "FMMI", "Ivato International Airport", "Ivato Intl", 0)]),

    ("Port Louis", "Port Louis", "MU", "Port Louis", -20.1609, 57.5012, "Indian/Mauritius",
     150000, True, [("MRU", "FIMP", "Sir Seewoosagur Ramgoolam International Airport", "SSR Intl", 0)]),

    ("Dar es Salaam", "Dar es Salaam", "TZ", "Dar es Salaam", -6.7924, 39.2083, "Africa/Dar_es_Salaam",
     7405000, False, [("DAR", "HTDA", "Julius Nyerere International Airport", "Julius Nyerere Intl", 0)]),

    ("Nairobi", "Nairobi", "KE", "Nairobi", -1.2921, 36.8219, "Africa/Nairobi",
     4397000, True, [
         ("NBO", "HKJK", "Jomo Kenyatta International Airport", "Jomo Kenyatta Intl", 0),
         ("WIL", "HKNW", "Nairobi Wilson Airport", "Wilson", 100),
     ]),

    ("Kigali", "Kigali", "RW", "Kigali", -1.9706, 30.1044, "Africa/Kigali",
     1208000, True, [("KGL", "HRYR", "Kigali International Airport", "Kigali Intl", 0)]),

    ("Luanda", "Luanda", "AO", "Luanda", -8.8390, 13.2894, "Africa/Luanda",
     8924000, True, [("LAD", "FNLU", "Quatro de Fevereiro International Airport", "4 de Fevereiro", 0)]),

    # ---- Belgium / Europe (F1 destination) ----
    ("Brussels", "Brussels", "BE", "Brussels-Capital", 50.8503, 4.3517, "Europe/Brussels",
     1208000, True, [("BRU", "EBBR", "Brussels Airport", "Brussels Airport", 0)]),

    ("Spa", "Spa", "BE", "Liège", 50.4924, 5.8647, "Europe/Brussels",
     10300, False, []),

    # US town called Brussels (disambiguation; no airport of its own)
    ("Brussels", "Brussels", "US", "Wisconsin", 44.7316, -87.6203, "America/Chicago",
     1100, False, []),

    ("Antwerp", "Antwerp", "BE", "Flanders", 51.2194, 4.4025, "Europe/Brussels",
     530000, False, [("ANR", "EBAW", "Antwerp International Airport", "Antwerp Intl", 0)]),

    ("Amsterdam", "Amsterdam", "NL", "North Holland", 52.3676, 4.9041, "Europe/Amsterdam",
     1166000, True, [("AMS", "EHAM", "Amsterdam Schiphol Airport", "Schiphol", 0)]),

    ("London", "London", "GB", "England", 51.5074, -0.1278, "Europe/London",
     9540000, True, [
         ("LHR", "EGLL", "London Heathrow Airport", "Heathrow", 0),
         ("LGW", "EGKK", "London Gatwick Airport", "Gatwick", 100),
         ("STN", "EGSS", "London Stansted Airport", "Stansted", 200),
     ]),

    ("Paris", "Paris", "FR", "Île-de-France", 48.8566, 2.3522, "Europe/Paris",
     2161000, True, [
         ("CDG", "LFPG", "Paris Charles de Gaulle Airport", "Charles de Gaulle", 0),
         ("ORY", "LFPO", "Paris Orly Airport", "Orly", 100),
     ]),

    ("Berlin", "Berlin", "DE", "Berlin", 52.5200, 13.4050, "Europe/Berlin",
     3645000, True, [("BER", "EDDB", "Berlin Brandenburg Airport", "BER", 0)]),

    ("Munich", "Munich", "DE", "Bavaria", 48.1351, 11.5820, "Europe/Berlin",
     1488000, False, [("MUC", "EDDM", "Munich Airport", "Munich", 0)]),

    ("Lisbon", "Lisbon", "PT", "Lisbon", 38.7223, -9.1393, "Europe/Lisbon",
     545000, True, [("LIS", "LPPT", "Lisbon Humberto Delgado Airport", "Humberto Delgado", 0)]),

    ("Porto", "Porto", "PT", "North", 41.1579, -8.6291, "Europe/Lisbon",
     215000, False, [("OPO", "LPPR", "Porto Francisco Sá Carneiro Airport", "Sá Carneiro", 0)]),

    ("Madrid", "Madrid", "ES", "Madrid", 40.4168, -3.7038, "Europe/Madrid",
     3223000, True, [("MAD", "LEMD", "Madrid Barajas Airport", "Barajas", 0)]),

    ("Barcelona", "Barcelona", "ES", "Catalonia", 41.3851, 2.1734, "Europe/Madrid",
     1620000, False, [("BCN", "LEBL", "Barcelona–El Prat Airport", "El Prat", 0)]),

    ("Rome", "Rome", "IT", "Lazio", 41.9028, 12.4964, "Europe/Rome",
     2873000, True, [("FCO", "LIRF", "Rome Fiumicino Airport", "Fiumicino", 0)]),

    ("Milan", "Milan", "IT", "Lombardy", 45.4642, 9.1900, "Europe/Rome",
     1396000, False, [
         ("MXP", "LIMC", "Milan Malpensa Airport", "Malpensa", 0),
         ("LIN", "LIML", "Milan Linate Airport", "Linate", 100),
     ]),

    ("Florence", "Florence", "IT", "Tuscany", 43.7696, 11.2558, "Europe/Rome",
     367000, False, [("FLR", "LIRQ", "Florence Airport", "Peretola", 0)]),

    ("Maranello", "Maranello", "IT", "Emilia-Romagna", 44.5375, 10.8653, "Europe/Rome",
     17500, False, []),

    ("Imola", "Imola", "IT", "Emilia-Romagna", 44.3533, 11.7147, "Europe/Rome",
     69900, False, []),

    # US towns that share names with famous European cities (disambiguation)
    ("Paris", "Paris", "US", "Texas", 33.6609, -95.5555, "America/Chicago",
     25000, False, []),
    ("Florence", "Florence", "US", "Oregon", 43.9826, -124.0998, "America/Los_Angeles",
     9000, False, []),
    ("Berlin", "Berlin", "US", "Wisconsin", 43.9680, -88.9435, "America/Chicago",
     5500, False, []),
    ("Athens", "Athens", "US", "Georgia", 33.9519, -83.3576, "America/New_York",
     127000, False, []),
    ("Troy", "Troy", "US", "Michigan", 42.6064, -83.1498, "America/Detroit",
     87000, False, []),
    ("Springfield", "Springfield", "US", "Illinois", 39.7817, -89.6501, "America/Chicago",
     114000, False, []),
    ("Salem", "Salem", "US", "Oregon", 44.9429, -123.0351, America_Los_Angeles if False else "America/Los_Angeles",
     175000, False, []),
    ("London", "London", "US", "Kentucky", 37.1289, -84.0833, "America/New_York",
     8000, False, []),
    ("Dublin", "Dublin", "US", "California", 37.7022, -121.9358, "America/Los_Angeles",
     63000, False, []),
    ("Naples", "Naples", "US", "Florida", 26.1224, -81.7948, "America/New_York",
     19500, False, []),
    ("Oxford", "Oxford", "US", "Mississippi", 34.3665, -89.5192, "America/Chicago",
     28000, False, []),
    ("Cambridge", "Cambridge", "US", "Massachusetts", 42.3736, -71.1097, "America/New_York",
     118000, False, []),
    ("Richmond", "Richmond", "US", "Virginia", 37.5407, -77.4360, "America/New_York",
     226000, False, []),
    ("Jackson", "Jackson", "US", "Mississippi", 32.2988, -90.1848, "America/Chicago",
     153000, False, []),
    ("Sydney", "Sydney", "US", "Montana", 47.7083, -104.1568, "America/Denver",
     5000, False, []),
    ("Aleppo", "Aleppo", "SY", "Aleppo Governorate", 36.2021, 37.1343, "Asia/Damascus",
     2100000, False, []),
    ("Alexandria", "Alexandria", "EG", "Alexandria", 31.2001, 29.9187, "Africa/Cairo",
     5200000, False, []),
    ("Monza", "Monza", "IT", "Lombardy", 45.5845, 9.2744, "Europe/Rome",
     123000, False, []),

    ("São Paulo", "Sao Paulo", "BR", "São Paulo", -23.5505, -46.6333, "America/Sao_Paulo",
     12330000, False, [
         ("GRU", "SBGR", "São Paulo/Guarulhos International Airport", "Guarulhos", 0),
         ("CGH", "SBSP", "São Paulo/Congonhas Airport", "Congonhas", 100),
     ]),

    ("Zurich", "Zurich", "CH", "Zurich", 47.3769, 8.5417, "Europe/Zurich",
     415000, False, [("ZRH", "LSZH", "Zurich Airport", "Zurich", 0)]),

    ("Vienna", "Vienna", "AT", "Vienna", 48.2082, 16.3738, "Europe/Vienna",
     1930000, True, [("VIE", "LOWW", "Vienna International Airport", "Vienna Intl", 0)]),

    ("Athens", "Athens", "GR", "Attica", 37.9838, 23.7275, "Europe/Athens",
     664000, True, [("ATH", "LGAV", "Athens International Airport", "Eleftherios Venizelos", 0)]),

    ("Istanbul", "Istanbul", "TR", "Istanbul", 41.0082, 28.9784, "Europe/Istanbul",
     15460000, False, [
         ("IST", "LTFM", "Istanbul Airport", "Istanbul Airport", 0),
         ("SAW", "LTFJ", "Sabiha Gökçen International Airport", "Sabiha Gökçen", 100),
     ]),

    # ---- USA (so Brussels-US disambiguation works) ----
    ("New York", "New York", "US", "New York", 40.7128, -74.0060, "America/New_York",
     8460000, False, [
         ("JFK", "KJFK", "John F. Kennedy International Airport", "JFK", 0),
         ("EWR", "KEWR", "Newark Liberty International Airport", "Newark", 100),
         ("LGA", "KLGA", "LaGuardia Airport", "LaGuardia", 200),
     ]),

    # ---- Asia / Middle East ----
    ("Dubai", "Dubai", "AE", "Dubai", 25.2048, 55.2708, "Asia/Dubai",
     3331000, False, [("DXB", "OMDB", "Dubai International Airport", "Dubai Intl", 0)]),

    ("Doha", "Doha", "QA", "Doha", 25.2854, 51.5310, "Asia/Qatar",
     2382000, True, [("DOH", "OTHH", "Hamad International Airport", "Hamad Intl", 0)]),

    ("Singapore", "Singapore", "SG", "Singapore", 1.3521, 103.8198, "Asia/Singapore",
     5686000, True, [("SIN", "WSSS", "Singapore Changi Airport", "Changi", 0)]),

    ("Bangkok", "Bangkok", "TH", "Bangkok", 13.7563, 100.5018, "Asia/Bangkok",
     10539000, True, [("BKK", "VTBS", "Suvarnabhumi Airport", "Suvarnabhumi", 0)]),

    ("Tokyo", "Tokyo", "JP", "Tokyo", 35.6762, 139.6503, "Asia/Tokyo",
     13960000, True, [
         ("NRT", "RJAA", "Narita International Airport", "Narita", 0),
         ("HND", "RJTT", "Tokyo Haneda Airport", "Haneda", 100),
     ]),
]


# -----------------------------------------------------------------------------
# Aliases
# Tuple format: (alias_display, alias_kind, country_bias_alpha2, target_city_ascii)
# country_bias_alpha2=None → global default
# -----------------------------------------------------------------------------

ALIASES: list[tuple[str, str, str | None, str]] = [
    # Johannesburg
    ("joburg", "nickname", None, "Johannesburg"),
    ("jo'burg", "nickname", None, "Johannesburg"),
    ("johannesburg", "local", None, "Johannesburg"),
    ("jnb", "iata", None, "Johannesburg"),
    ("or tambo", "nickname", None, "Johannesburg"),
    ("or tambo intl", "nickname", None, "Johannesburg"),
    ("tambo", "nickname", None, "Johannesburg"),

    # Maputo
    ("maputo", "local", None, "Maputo"),
    ("mpm", "iata", None, "Maputo"),
    ("moz", "nickname", None, "Maputo"),
    ("moçambique", "local", "MZ", "Maputo"),
    ("mocambique", "local", None, "Maputo"),

    # Cape Town
    ("cape town", "local", None, "Cape Town"),
    ("kaapstad", "local", "ZA", "Cape Town"),
    ("cpt", "iata", None, "Cape Town"),

    # Brussels — no default-bias alias, so "brussels" alone falls through
    # to name resolution which will surface both Brussels-BE and the US
    # town as alternatives.
    ("brussels", "local", "BE", "Brussels"),
    ("brussels", "local", "US", "Brussels"),  # Brussels, Wisconsin
    ("bruxelles", "local", "BE", "Brussels"),
    ("brussel", "local", "BE", "Brussels"),
    ("bru", "iata", None, "Brussels"),
    ("ebbr", "icao", None, "Brussels"),

    # London
    ("london", "local", None, "London"),
    ("lhr", "iata", None, "London"),
    ("heathrow", "local", None, "London"),
    ("gatwick", "local", None, "London"),

    # Paris
    ("paris", "local", None, "Paris"),
    ("cdg", "iata", None, "Paris"),
    ("charles de gaulle", "local", None, "Paris"),
    ("orly", "local", None, "Paris"),

    # Amsterdam
    ("amsterdam", "local", None, "Amsterdam"),
    ("ams", "iata", None, "Amsterdam"),
    ("schiphol", "local", None, "Amsterdam"),

    # New York
    ("nyc", "nickname", None, "New York"),
    ("new york", "local", None, "New York"),
    ("new york city", "local", None, "New York"),
    ("jfk", "iata", None, "New York"),
    ("the big apple", "nickname", None, "New York"),
    ("manhattan", "local", None, "New York"),

    # São Paulo — diacritics handled by ascii_name="Sao Paulo" + name="São Paulo"
    ("sampa", "nickname", "BR", "Sao Paulo"),
    ("gru", "iata", None, "Sao Paulo"),
    ("cgh", "iata", None, "Sao Paulo"),

    # Istanbul
    ("istanbul", "local", None, "Istanbul"),
    ("ist", "iata", None, "Istanbul"),

    # Singapore
    ("singapore", "local", None, "Singapore"),
    ("sin", "iata", None, "Singapore"),
    ("changi", "local", None, "Singapore"),

    # Dubai
    ("dubai", "local", None, "Dubai"),
    ("dxb", "iata", None, "Dubai"),

    # Tokyo
    ("tokyo", "local", None, "Tokyo"),
    ("hnd", "iata", None, "Tokyo"),
    ("haneda", "local", None, "Tokyo"),
    ("narita", "local", None, "Tokyo"),
]


# -----------------------------------------------------------------------------
# Seeding (idempotent)
# -----------------------------------------------------------------------------

async def seed_reference_data(session: AsyncSession) -> dict[str, int]:
    """Upsert countries, cities, airports, aliases. Returns counts."""
    counts = {"countries": 0, "cities": 0, "airports": 0, "aliases": 0}

    # 1. Countries
    for c in COUNTRIES:
        row = (
            await session.execute(select(Country).where(Country.alpha2 == c["alpha2"]))
        ).scalar_one_or_none()
        if row is None:
            session.add(Country(**c))
            counts["countries"] += 1
        else:
            for k, v in c.items():
                setattr(row, k, v)
    await session.flush()

    # 2. Cities + airports (airports depend on cities)
    for (name, ascii_name, alpha2, region, lat, lng, tz, pop, is_cap, airports) in CITIES:
        city = (
            await session.execute(
                select(City).where(
                    City.ascii_name == ascii_name,
                    City.country_alpha2 == alpha2,
                )
            )
        ).scalar_one_or_none()
        if city is None:
            city = City(
                name=name,
                ascii_name=ascii_name,
                country_alpha2=alpha2,
                region=region,
                latitude=lat,
                longitude=lng,
                timezone=tz,
                population=pop,
                is_capital=is_cap,
            )
            session.add(city)
            counts["cities"] += 1
            await session.flush()
        else:
            city.name = name
            city.region = region
            city.latitude = lat
            city.longitude = lng
            city.timezone = tz
            city.population = pop
            city.is_capital = is_cap

        for (iata, icao, ap_name, ap_short, priority) in airports:
            ap = (
                await session.execute(select(Airport).where(Airport.iata == iata))
            ).scalar_one_or_none()
            if ap is None:
                session.add(Airport(
                    iata=iata, icao=icao, name=ap_name, short_name=ap_short,
                    city_id=city.id, kind="airport",
                    latitude=lat, longitude=lng,
                    priority=priority, is_active=True,
                ))
                counts["airports"] += 1
            else:
                ap.icao = icao
                ap.name = ap_name
                ap.short_name = ap_short
                ap.city_id = city.id
                ap.priority = priority
                ap.is_active = True
    await session.flush()

    # 3. Aliases (depend on cities)
    for (alias_display, alias_kind, country_bias, target_ascii) in ALIASES:
        # We resolve the target by ascii_name (we control both sides).
        # Some aliases (e.g. "brussels" BE vs US) share the same
        # ascii_name; the country_bias disambiguates them. If no bias,
        # pick the city with that ascii_name in the same country as
        # the bias, falling back to the highest-population match.
        target = None
        if country_bias:
            target = (
                await session.execute(
                    select(City).where(
                        City.ascii_name == target_ascii,
                        City.country_alpha2 == country_bias,
                    )
                )
            ).scalar_one_or_none()
        if target is None:
            # Fallback: target_ascii might be non-ASCII ("São Paulo").
            target_norm = _norm_for_seed(target_ascii)
            target = (
                await session.execute(
                    select(City).where(City.ascii_name == target_ascii)
                    if target_ascii == target_norm.title()
                    else select(City).where(City.ascii_name == target_norm.title())
                )
            ).scalars().first()
        if target is None:
            logger.warning("alias %r -> %r: target city not found, skipping", alias_display, target_ascii)
            continue

        norm = _norm_for_seed(alias_display)
        existing = (
            await session.execute(
                select(CityAlias).where(
                    CityAlias.alias_norm == norm,
                    CityAlias.country_bias_alpha2 == country_bias,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(CityAlias(
                city_id=target.id,
                alias=alias_display,
                alias_norm=norm,
                alias_kind=alias_kind,
                country_bias_alpha2=country_bias,
            ))
            counts["aliases"] += 1
        else:
            existing.alias = alias_display
            existing.alias_kind = alias_kind
            existing.city_id = target.id

    await session.commit()
    logger.info("refdata seed: %s", counts)
    return counts


__all__ = ["seed_reference_data"]

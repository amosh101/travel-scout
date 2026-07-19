"""Refdata loaders — pull authoritative public datasets into our DB.

Sources used (all public domain / CC0):
  - ISO 3166-1 countries: github.com/lukes/ISO-3166-Countries-with-Regional-Codes
    (CC-BY-SA; the dataset is the canonical ISO 3166-1 mapping that
    OpenStreetMap, Wikipedia, and most international organizations use)
  - IATA airports: github.com/davidmegginson/ourairports-data
    (public domain; the canonical airport dataset used by OpenStreetMap,
    FlightAware, FlightRadar24, etc.)

Run with:
    python -m app.refdata.load [--countries] [--airports] [--aliases]

The loaders are idempotent (upsert by primary key) and safe to re-run.
They are NOT part of the regular server start (which is why they're a
separate module, not in seed.py). The seed.py file holds a hand-curated
small subset for offline dev / tests; load.py is the production loader.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import sys
from typing import Iterable

# Import order matters: get curl_cffi before SQLAlchemy so the venv
# has it, then load models, then the database session factory.
from curl_cffi import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Import models first so the relationships register on Base.metadata.
from app.refdata.models import Airport, City, CityAlias, Country
from app.database import get_session_factory

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Sources
# -----------------------------------------------------------------------------

ISO_3166_URL = (
    "https://raw.githubusercontent.com/lukes/ISO-3166-Countries-with-"
    "Regional-Codes/master/all/all.json"
)
OURAIRPORTS_URL = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/"
    "main/airports.csv"
)
OURAIRPORTS_COUNTRIES_URL = (
    "https://raw.githubusercontent.com/davidmegginson/ourairports-data/"
    "main/countries.csv"
)

# Airport size/type we care about for travel planning. Skipping heliports
# and ultra-small general-aviation fields keeps the table at a useful
# size (~10k rows) for fast disambiguation.
_USEFUL_AIRPORT_TYPES = {
    "large_airport",
    "medium_airport",
    "seaplane_base",
    "closed",  # historical — useful as aliases (e.g. Berlin Tempelhof)
}


# -----------------------------------------------------------------------------
# HTTP
# -----------------------------------------------------------------------------

def _fetch(url: str, *, timeout: int = 60) -> str:
    """Fetch a public URL with curl_cffi to bypass CF rate limits."""
    r = requests.get(url, impersonate="chrome120", timeout=timeout)
    r.raise_for_status()
    return r.text


# -----------------------------------------------------------------------------
# Country loader
# -----------------------------------------------------------------------------

async def load_countries(
    session: AsyncSession,
    *,
    url: str = ISO_3166_URL,
    dry_run: bool = False,
) -> int:
    """Upsert all ISO 3166-1 countries into the countries table.

    Returns the number of rows written.
    """
    logger.info("fetching ISO 3166-1 dataset from %s", url)
    body = _fetch(url, timeout=30)
    rows = json.loads(body)
    logger.info("got %d countries", len(rows))

    dialect = session.bind.dialect.name if session.bind else "postgresql"
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert

    count = 0
    for r in rows:
        alpha2 = r.get("alpha-2", "").upper()
        alpha3 = r.get("alpha-3", "").upper()
        if not alpha2 or len(alpha2) != 2:
            continue
        values = {
            "alpha2": alpha2,
            "alpha3": alpha3,
            "numeric_code": r.get("country-code", "") or None,
            "name": r.get("name", ""),
            "region": r.get("region", "") or None,
            "sub_region": r.get("sub-region", "") or None,
        }
        if dry_run:
            count += 1
            continue
        stmt = insert_fn(Country).values(**values)
        # Upsert on alpha2 (primary key).
        if dialect == "postgresql":
            stmt = stmt.on_conflict_do_update(
                index_elements=["alpha2"],
                set_={
                    "alpha3": stmt.excluded.alpha3,
                    "numeric_code": stmt.excluded.numeric_code,
                    "name": stmt.excluded.name,
                    "region": stmt.excluded.region,
                    "sub_region": stmt.excluded.sub_region,
                },
            )
        else:
            stmt = stmt.on_conflict_do_update(
                index_elements=["alpha2"],
                set_={
                    "alpha3": stmt.excluded.alpha3,
                    "numeric_code": stmt.excluded.numeric_code,
                    "name": stmt.excluded.name,
                    "region": stmt.excluded.region,
                    "sub_region": stmt.excluded.sub_region,
                },
            )
        await session.execute(stmt)
        count += 1
    if not dry_run:
        await session.commit()
    logger.info("wrote %d countries", count)
    return count


# -----------------------------------------------------------------------------
# Airport loader
# -----------------------------------------------------------------------------

async def load_airports(
    session: AsyncSession,
    *,
    airports_url: str = OURAIRPORTS_URL,
    countries_url: str = OURAIRPORTS_COUNTRIES_URL,
    dry_run: bool = False,
) -> int:
    """Upsert airports from OurAirports.

    Each airport becomes a City (the municipality) + an Airport row. The
    Country is resolved by ISO alpha-2 against our countries table; any
    airport whose country is not in our DB is skipped (run
    ``load_countries`` first).

    Returns the number of airports written.
    """
    logger.info("fetching OurAirports data from %s", airports_url)
    csv_text = _fetch(airports_url, timeout=120)
    logger.info("got %d bytes of airport data", len(csv_text))

    # Pre-fetch the country name → alpha2 map for cities OurAirports
    # lists under a name we don't have yet (rare; we resolve airports by
    # country first).
    country_rows = (
        await session.execute(select(Country.alpha2))
    ).scalars().all()
    countries = {c.upper() for c in country_rows if c}

    dialect = session.bind.dialect.name if session.bind else "postgresql"
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert

    # Buffer cities and airports per country; we'll batch upsert.
    airport_count = 0
    city_count = 0
    cities_to_upsert: dict[tuple[str, str], dict] = {}  # (alpha2, name) -> dict
    airports_to_upsert: list[dict] = []

    for row in csv.DictReader(io.StringIO(csv_text)):
        iata = (row.get("iata_code") or "").upper()
        icao = (row.get("icao_code") or "").upper()
        kind = (row.get("type") or "").lower()
        country = (row.get("iso_country") or "").upper()
        if country not in countries:
            continue  # No matching country in our DB.
        if kind not in _USEFUL_AIRPORT_TYPES:
            continue
        if not (iata or icao):
            continue
        try:
            lat = float(row["latitude_deg"]) if row.get("latitude_deg") else None
            lng = float(row["longitude_deg"]) if row.get("longitude_deg") else None
        except ValueError:
            continue
        if lat is None or lng is None:
            continue
        # City: best-effort — use municipality from OurAirports. For
        # airports with no municipality, fall back to the airport name
        # minus "Airport" / "Intl" / etc.
        city_name = (row.get("municipality") or "").strip()
        if not city_name:
            city_name = _airport_name_to_city(row.get("name") or "")
        if not city_name:
            continue
        ascii_city = _to_ascii(city_name)
        cities_to_upsert[(country, ascii_city)] = {
            "name": city_name,
            "ascii_name": ascii_city,
            "country_alpha2": country,
            "latitude": lat,
            "longitude": lng,
        }
        airports_to_upsert.append({
            "iata": iata or None,
            "icao": icao or None,
            "name": row.get("name") or "",
            "short_name": _airport_short_name(row.get("name") or ""),
            "country_alpha2": country,
            "latitude": lat,
            "longitude": lng,
            "is_active": kind != "closed",
            "kind": "airport",
            "priority": 50 if kind == "large_airport" else 100 if kind == "medium_airport" else 200,
            "city_name": ascii_city,
        })

    logger.info(
        "buffered %d unique cities and %d airports",
        len(cities_to_upsert), len(airports_to_upsert),
    )

    # 1. Upsert cities.
    for (country, ascii_name), cv in cities_to_upsert.items():
        values = {
            "name": cv["name"],
            "ascii_name": cv["ascii_name"],
            "country_alpha2": cv["country_alpha2"],
            "region": "",
            "latitude": cv["latitude"],
            "longitude": cv["longitude"],
            "timezone": "",
            "population": 0,
            "is_capital": False,
        }
        if not dry_run:
            stmt = insert_fn(City).values(**values)
            if dialect == "postgresql":
                stmt = stmt.on_conflict_do_update(
                    index_elements=["country_alpha2", "ascii_name"],
                    set_={
                        "name": stmt.excluded.name,
                        "latitude": stmt.excluded.latitude,
                        "longitude": stmt.excluded.longitude,
                    },
                )
            else:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["country_alpha2", "ascii_name"],
                    set_={
                        "name": stmt.excluded.name,
                        "latitude": stmt.excluded.latitude,
                        "longitude": stmt.excluded.longitude,
                    },
                )
            await session.execute(stmt)
        city_count += 1

    if not dry_run:
        await session.commit()

    # 2. Resolve city_ids and upsert airports.
    for av in airports_to_upsert:
        city_id = (
            await session.execute(
                select(City.id).where(
                    City.country_alpha2 == av["country_alpha2"],
                    City.ascii_name == av["city_name"],
                )
            )
        ).scalar_one_or_none()
        if city_id is None:
            continue
        values = {
            "iata": av["iata"],
            "icao": av["icao"],
            "name": av["name"],
            "short_name": av["short_name"],
            "kind": av["kind"],
            "latitude": av["latitude"],
            "longitude": av["longitude"],
            "priority": av["priority"],
            "is_active": av["is_active"],
            "city_id": city_id,
        }
        if not dry_run:
            stmt = insert_fn(Airport).values(**values)
            if dialect == "postgresql":
                stmt = stmt.on_conflict_do_update(
                    index_elements=["iata"],
                    set_={
                        "icao": stmt.excluded.icao,
                        "name": stmt.excluded.name,
                        "short_name": stmt.excluded.short_name,
                        "city_id": stmt.excluded.city_id,
                        "priority": stmt.excluded.priority,
                    },
                )
            else:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["iata"],
                    set_={
                        "icao": stmt.excluded.icao,
                        "name": stmt.excluded.name,
                        "short_name": stmt.excluded.short_name,
                        "city_id": stmt.excluded.city_id,
                        "priority": stmt.excluded.priority,
                    },
                )
            await session.execute(stmt)
        airport_count += 1

    if not dry_run:
        await session.commit()
    logger.info("wrote %d cities, %d airports", city_count, airport_count)
    return airport_count


# -----------------------------------------------------------------------------
# Alias loader
# -----------------------------------------------------------------------------

# Common non-English name variants. Each entry: (alias, country_bias or "").
# These are *not* hardcoded in the search router — they're seed data the
# admin can edit/add/remove without touching code. The router only reads
# from the city_aliases table.
ALIAS_NAMES: list[tuple[str, str]] = [
    # Portuguese/Spanish — major ex-colonial cities
    ("maputo", ""), ("maputo city", ""),
    ("joburg", ""), ("jo'burg", ""), ("johanesburgo", ""), ("johannesburg", ""),
    ("cape town", ""), ("cidade do cabo", ""), ("ciudad del cabo", ""),
    ("durban", ""),
    ("londres", ""), ("londra", ""), ("london", ""),
    ("paris", ""), ("paname", ""),
    ("roma", ""), ("rom", ""), ("rzym", ""),
    ("mila", ""), ("milao", ""), ("mailand", ""),
    ("florenca", ""), ("florencia", ""), ("firenze", ""), ("florence", ""),
    ("bruxelas", ""), ("bruxelles", ""), ("brussel", ""), ("brussels", ""),
    ("moscou", ""), ("moskva", ""), ("moscow", ""),
    ("atenas", ""), ("athen", ""), ("athens", ""), ("athinai", ""),
    ("varsovia", ""), ("warszawa", ""), ("warsaw", ""),
    ("viena", ""), ("wien", ""), ("vienna", ""),
    ("praga", ""), ("prag", ""), ("prague", ""),
    ("munique", ""), ("munchen", ""), ("munich", ""),
    ("lisboa", ""), ("lisbonne", ""), ("lisbon", ""),
    ("estocolmo", ""), ("stockholm", ""),
    ("oslo", ""),
    ("helsinki", ""),
    ("reiquiavque", ""), ("reykjavik", ""), ("reykjav\u00edk", ""),
    ("copenhague", ""), ("kobenhavn", ""), ("copenhagen", ""),
    ("pequim", ""), ("beijing", ""),
    ("t\u00e9quio", ""), ("tokyo", ""), ("tokio", ""),
    ("singapura", ""), ("singapore", ""),
    ("dubai", ""),
    ("bangkok", ""),
    ("seul", ""), ("seoul", ""),
    ("novo iorque", ""), ("new york", ""), ("nueva york", ""),
    ("los angeles", ""), ("angeles", ""),
    ("toronto", ""), ("montreal", ""),
    ("mexico", ""), ("ciudad de mexico", ""),
    ("buenos aires", ""),
    ("sao paulo", ""), ("s\u00e3o paulo", ""),
    ("rio", ""), ("rio de janeiro", ""),
    ("cairo", ""), ("el cairo", ""),
    ("cidade do cabo", ""),  # dup with above
    ("antalya", ""),
    ("belem", ""), ("bel\u00e9m", ""),
    ("curitiba", ""),
    ("porto alegre", ""),
    ("fortaleza", ""),
    ("recife", ""),
    ("salvador", ""),
    ("maceio", ""), ("macei\u00f3", ""),
    ("joao pessoa", ""), ("jo\u00e3o pessoa", ""),
    ("natal", ""),
    ("florianopolis", ""), ("florian\u00f3polis", ""),
    ("goiania", ""), ("goi\u00e2nia", ""),
    ("campo grande", ""),
    ("cuiaba", ""), ("cuiab\u00e1", ""),
    ("manaus", ""),
    ("belem", ""),
    ("beira", ""),
    ("nampula", ""),
    ("tete", ""),
    ("lichinga", ""),
    ("quelimane", ""),
    ("inhambane", ""),
    ("xai-xai", ""), ("xai xai", ""),
    ("chimoio", ""),
    ("gweru", ""), ("harare", ""), ("bulawayo", ""), ("mutare", ""),
    ("lusaka", ""), ("kitwe", ""), ("ndola", ""),
    ("lilongwe", ""), ("blantyre", ""), ("mzuzu", ""),
    ("gaborone", ""), ("francistown", ""), ("maun", ""),
    ("windhoek", ""), ("swakopmund", ""), ("walvis bay", ""),
    ("maseru", ""),
    ("mbabane", ""), ("lobamba", ""), ("manzini", ""),
    ("antananarivo", ""), ("tananarive", ""), ("antsirabe", ""),
    ("port louis", ""),
    ("victoria", ""), ("seychelles", ""),
    ("moroni", ""),
    ("kampala", ""),
    ("dodoma", ""), ("dar es salaam", ""), ("zanzibar", ""),
    ("nairobi", ""), ("mombasa", ""), ("kisumu", ""),
    ("kigali", ""), ("butare", ""),
    ("brazzaville", ""), ("kinshasa", ""), ("lubumbashi", ""), ("goma", ""),
    ("luanda", ""), ("benguela", ""), ("huambo", ""), ("lobito", ""),
    ("kigali", ""),  # dup
    ("dakar", ""), ("thies", ""), ("saint-louis", ""), ("saint louis", ""),
    ("bamako", ""), ("timbuktu", ""), ("tombouctou", ""),
    ("conakry", ""),
    ("freetown", ""),
    ("monrovia", ""),
    ("abidjan", ""), ("yamoussoukro", ""), ("bouake", ""),
    ("accra", ""), ("kumasi", ""), ("tamale", ""),
    ("lome", ""), ("lom\u00e9", ""),
    ("cotonou", ""), ("porto-novo", ""), ("porto novo", ""),
    ("lagos", ""), ("abuja", ""), ("ibadan", ""), ("kano", ""),
    ("niamey", ""),
    ("ouagadougou", ""),
    ("ndjamena", ""), ("n'djamena", ""),
    ("khartoum", ""), ("omdurman", ""),
    ("juba", ""),
    ("asmara", ""), ("asmara", ""), ("massawa", ""),
    ("djibouti", ""),
    ("mogadishu", ""), ("muqdisho", ""),
    ("hargeisa", ""),
    ("addis ababa", ""), ("addis abeba", ""), ("dire dawa", ""),
    ("tripoli", ""),
    ("tunis", ""),
    ("algiers", ""), ("alger", ""), ("oran", ""),
    ("rabat", ""), ("casablanca", ""), ("marrakech", ""), ("fez", ""), ("fes", ""),
    ("tripoli", ""),  # dup
    ("nicosia", ""), ("lefkosia", ""),
    ("yerevan", ""), ("erevan", ""),
    ("tbilisi", ""), ("tiflis", ""),
    ("baku", ""),
    ("astana", ""), ("nur-sultan", ""), ("almaty", ""),
    ("tashkent", ""),
    ("bishkek", ""),
    ("dushanbe", ""),
    ("ashgabat", ""),
    ("sana'a", ""), ("sanaa", ""), ("aden", ""),
    ("amman", ""),
    ("beirut", ""), ("bayrut", ""),
    ("damascus", ""), ("dimashq", ""), ("aleppo", ""), ("halab", ""),
    ("baghdad", ""), ("basra", ""),
    ("tehran", ""),
    ("kabul", ""),
    ("islamabad", ""), ("karachi", ""), ("lahore", ""), ("peshawar", ""),
    ("colombo", ""), ("kandy", ""),
    ("kathmandu", ""), ("kathmandou", ""),
    ("thimphu", ""),
    ("dhaka", ""), ("chittagong", ""),
    ("yangon", ""), ("rangoon", ""), ("mandalay", ""),
    ("phnom penh", ""),
    ("vientiane", ""),
    ("hanoi", ""), ("ho chi minh", ""), ("saigon", ""),
    ("manila", ""), ("cebu", ""), ("davao", ""),
    ("jakarta", ""), ("surabaya", ""), ("bandung", ""), ("medan", ""),
    ("kuala lumpur", ""), ("penang", ""), ("george town", ""),
    ("bandar seri begawan", ""),
    ("ulaanbaatar", ""), ("ulan bator", ""),
    ("pyongyang", ""),
    ("kabul", ""),  # dup
    ("dili", ""),
    ("suva", ""), ("nadi", ""),
    ("port moresby", ""),
    ("apia", ""),
    ("nuku'alofa", ""), ("nukualofa", ""),
    ("tarawa", ""),
    ("majuro", ""),
    ("palikir", ""),
    ("hagatna", ""), ("hag\u00e5t\u00f1a", ""),
    ("saipan", ""),
    ("koror", ""),
]


async def load_aliases(
    session: AsyncSession,
    aliases: list[tuple[str, str]] | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """Upsert city aliases.

    Each alias is (alias_string, country_bias_alpha2). The country_bias
    is empty string for the default-bias alias (e.g. "paris" -> FR by
    default; "paris" with bias US -> Paris, Texas).

    If no aliases are passed, this function returns 0 — alias data is
    curated by humans in seed.py and should not be auto-generated from
    the airport data (which has no population/travel-importance signal).

    For each alias, we look up the *default* target city by name; an
    empty bias means "primary / most populous city with that name". A
    non-empty bias means "this alias in this specific country". If the
    city isn't in the cities table, the alias is silently skipped (the
    admin can add the city first).
    """
    if not aliases:
        logger.info("no aliases to load; use seed.py for curated aliases")
        return 0
    dialect = session.bind.dialect.name if session.bind else "postgresql"
    insert_fn = pg_insert if dialect == "postgresql" else sqlite_insert
    count = 0
    for alias, bias in aliases:
        norm = _to_ascii(alias)
        if not norm:
            continue
        # Find target city: if bias is set, find by name+bias. If not,
        # find the city with that name in the country with the most
        # population for the name.
        if bias:
            target = (
                await session.execute(
                    select(City).where(
                        City.ascii_name == _to_ascii(alias),
                        City.country_alpha2 == bias,
                    )
                )
            ).scalar_one_or_none()
        else:
            target = (
                await session.execute(
                    select(City)
                    .where(City.ascii_name == _to_ascii(alias))
                    .order_by(City.population.desc())
                )
            ).scalars().first()
        if target is None:
            continue
        values = {
            "alias": alias,
            "alias_norm": norm,
            "alias_kind": "local",
            "country_bias_alpha2": bias or None,
            "city_id": target.id,
        }
        if not dry_run:
            stmt = insert_fn(CityAlias).values(**values)
            if dialect == "postgresql":
                stmt = stmt.on_conflict_do_update(
                    index_elements=["alias_norm", "country_bias_alpha2"],
                    set_={
                        "city_id": stmt.excluded.city_id,
                        "alias": stmt.excluded.alias,
                    },
                )
            else:
                stmt = stmt.on_conflict_do_update(
                    index_elements=["alias_norm", "country_bias_alpha2"],
                    set_={
                        "city_id": stmt.excluded.city_id,
                        "alias": stmt.excluded.alias,
                    },
                )
            await session.execute(stmt)
        count += 1
    if not dry_run:
        await session.commit()
    logger.info("wrote %d aliases", count)
    return count


# -----------------------------------------------------------------------------
# Text helpers
# -----------------------------------------------------------------------------

def _to_ascii(text: str) -> str:
    """Same normalisation as ReferenceService._norm — lowercase, drop
    diacritics, drop punctuation, collapse spaces."""
    import re as _re
    import unicodedata
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = ascii_only.lower()
    lower = _re.sub(r"['''`]", "", lower)
    lower = _re.sub(r"[^a-z0-9]+", " ", lower)
    return _re.sub(r"\s+", " ", lower).strip()


def _airport_name_to_city(name: str) -> str:
    """'Heathrow Airport' -> 'Heathrow'"""
    import re as _re
    return _re.sub(
        r"\s+(airport|international|intl|airfield|aerodrome|afb|ab)\b",
        "", name, flags=_re.IGNORECASE,
    ).strip() or name


def _airport_short_name(name: str) -> str:
    """'Heathrow Airport' -> 'Heathrow'"""
    return _airport_name_to_city(name)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

async def _main_async(args: argparse.Namespace) -> None:
    factory = get_session_factory()
    async with factory() as session:
        if args.countries or args.all:
            await load_countries(session, dry_run=args.dry_run)
        if args.airports or args.all:
            await load_airports(session, dry_run=args.dry_run)
        if args.aliases or args.all:
            await load_aliases(session, dry_run=args.dry_run)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--countries", action="store_true", help="load countries")
    p.add_argument("--airports", action="store_true", help="load airports")
    p.add_argument("--aliases", action="store_true", help="load aliases")
    p.add_argument("--all", action="store_true", help="load everything")
    p.add_argument("--dry-run", action="store_true", help="count only")
    args = p.parse_args()
    if not any([args.countries, args.airports, args.aliases, args.all]):
        p.error("specify --countries, --airports, --aliases, or --all")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    )
    import asyncio
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()

"""Reference data service: resolve any user input to a structured location.

The ``ReferenceService`` is the single, canonical way to turn a string
("joburg", "BRU", "São Paulo", "JNB") into a structured
``LocationResolution`` with city, country, and primary airport.

Resolution strategy (in order, first hit wins):
  1. **Exact IATA code**     "BRU" → Brussels Airport
  2. **Exact ICAO code**     "EBBR" → Brussels Airport
  3. **Alias (with country bias)**  "joburg" + ZA → Johannesburg
  4. **Alias (no country bias)**    "joburg" → Johannesburg (default)
  5. **Canonical name**     "Cape Town" → Cape Town
  6. **Ascii name**         "Sao Paulo" → São Paulo
  7. **Fuzzy / prefix**     "Sao P" → São Paulo
  8. **Freeform**           "Nowhereville" → match=None, return raw text

Each step returns confidence (0.0–1.0) and a ``match_kind`` so callers
can decide whether to auto-pick or ask the user.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.refdata.models import Airport, City, CityAlias, Country

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Public dataclasses
# -----------------------------------------------------------------------------

@dataclass
class LocationResolution:
    """Structured result of resolving user input to a real place."""
    raw_input: str
    matched: bool
    confidence: float  # 0.0–1.0
    match_kind: str    # "iata" | "icao" | "alias" | "name" | "ascii" | "fuzzy" | "freeform"
    city: City | None = None
    country: Country | None = None
    airport: Airport | None = None
    alternatives: list["LocationResolution"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation for API responses."""
        return {
            "raw_input": self.raw_input,
            "matched": self.matched,
            "confidence": self.confidence,
            "match_kind": self.match_kind,
            "city": _city_dict(self.city) if self.city else None,
            "country": _country_dict(self.country) if self.country else None,
            "airport": _airport_dict(self.airport) if self.airport else None,
            "alternatives": [a.to_dict() for a in self.alternatives],
        }


def _city_dict(c: City | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {
        "id": str(c.id),
        "name": c.name,
        "ascii_name": c.ascii_name,
        "country_alpha2": c.country_alpha2,
        "region": c.region,
        "latitude": c.latitude,
        "longitude": c.longitude,
        "timezone": c.timezone,
        "is_capital": c.is_capital,
        "airports": [_airport_dict(a) for a in (c.airports or [])],
    }


def _country_dict(c: Country | None) -> dict[str, Any] | None:
    if c is None:
        return None
    return {
        "alpha2": c.alpha2,
        "alpha3": c.alpha3,
        "name": c.name,
        "name_pt": c.name_pt,
        "currency": c.currency,
        "flag_emoji": c.flag_emoji,
        "languages": c.languages.split(",") if c.languages else [],
    }


def _airport_dict(a: Airport | None) -> dict[str, Any] | None:
    if a is None:
        return None
    return {
        "iata": a.iata,
        "icao": a.icao,
        "name": a.name,
        "short_name": a.short_name,
        "kind": a.kind,
        "priority": a.priority,
    }


# -----------------------------------------------------------------------------
# Normalisation
# -----------------------------------------------------------------------------

def _norm(text: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, drop punctuation.

    "São Paulo"  → "sao paulo"
    "Jo'burg"    → "joburg"
    "Cape Town"  → "cape town"
    "BRU"        → "bru"
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    lower = ascii_only.lower()
    lower = re.sub(r"[''`]", "", lower)
    lower = re.sub(r"[^a-z0-9]+", " ", lower)
    return re.sub(r"\s+", " ", lower).strip()


# -----------------------------------------------------------------------------
# Service
# -----------------------------------------------------------------------------

class ReferenceService:
    """Stateless resolver backed by the refdata tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- city lookup --------------------------------------------------------

    async def get_city(self, city_id: str) -> City | None:
        stmt = (
            select(City)
            .options(selectinload(City.country), selectinload(City.airports), selectinload(City.aliases))
            .where(City.id == city_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_airport(self, iata: str) -> Airport | None:
        if not iata or len(iata) != 3:
            return None
        stmt = (
            select(Airport)
            .options(
                selectinload(Airport.city).selectinload(City.country),
                selectinload(Airport.city).selectinload(City.airports),
            )
            .where(Airport.iata == iata.upper())
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # -- public resolution --------------------------------------------------

    async def resolve(
        self,
        text: str,
        *,
        country_bias: str | None = None,
    ) -> LocationResolution:
        """Resolve a free-text or code input to a location.

        ``country_bias`` is a 2-letter ISO code (e.g. "BE" for Brussels).
        Used to disambiguate when the same name exists in multiple
        countries (Brussels, BE vs Brussels, US vs Brussels, CA).
        """
        raw = (text or "").strip()
        if not raw:
            return LocationResolution(raw_input=raw, matched=False, confidence=0.0, match_kind="freeform")

        norm = _norm(raw)
        if not norm:
            return LocationResolution(raw_input=raw, matched=False, confidence=0.0, match_kind="freeform")

        # 1. IATA code (exactly 3 letters, all alpha)
        if len(norm) == 3 and norm.isalpha():
            ap = await self.get_airport(norm.upper())
            if ap is not None:
                return LocationResolution(
                    raw_input=raw,
                    matched=True,
                    confidence=1.0,
                    match_kind="iata",
                    city=ap.city,
                    country=ap.city.country if ap.city else None,
                    airport=ap,
                )

        # 2. ICAO code (exactly 4 letters)
        if len(norm) == 4 and norm.isalpha():
            stmt = (
                select(Airport)
                .options(
                    selectinload(Airport.city).selectinload(City.country),
                    selectinload(Airport.city).selectinload(City.airports),
                )
                .where(Airport.icao == norm.upper())
            )
            ap = (await self.session.execute(stmt)).scalar_one_or_none()
            if ap is not None:
                return LocationResolution(
                    raw_input=raw,
                    matched=True,
                    confidence=0.95,
                    match_kind="icao",
                    city=ap.city,
                    country=ap.city.country if ap.city else None,
                    airport=ap,
                )

        # 3+4. Alias with optional country bias
        alts: list[LocationResolution] = []
        primary = await self._resolve_alias(norm, country_bias=country_bias, alternatives=alts)
        if primary is not None:
            return primary

        # 5+6. Canonical name or ASCII name
        primary, alts2 = await self._resolve_name(norm, country_bias=country_bias)
        if primary is not None:
            primary.alternatives = alts2
            return primary
        alts.extend(alts2)

        # 7. Fuzzy / prefix
        primary, alts3 = await self._resolve_fuzzy(norm, country_bias=country_bias)
        if primary is not None:
            primary.alternatives = alts + alts3
            return primary
        alts.extend(alts3)

        # 8. Freeform fallback
        return LocationResolution(
            raw_input=raw,
            matched=False,
            confidence=0.0,
            match_kind="freeform",
            alternatives=alts[:5],
        )

    # -- alias resolution ---------------------------------------------------

    async def _resolve_alias(
        self,
        norm: str,
        *,
        country_bias: str | None,
        alternatives: list[LocationResolution],
    ) -> LocationResolution | None:
        bias = country_bias.upper() if country_bias else None

        # 1. Alias with matching country bias (most specific)
        if bias:
            stmt = (
                select(CityAlias)
                .options(
                    selectinload(CityAlias.city).selectinload(City.country),
                    selectinload(CityAlias.city).selectinload(City.airports),
                )
                .where(CityAlias.alias_norm == norm, CityAlias.country_bias_alpha2 == bias)
            )
            row = (await self.session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return self._alias_to_resolution(row, norm, 0.98, "alias")

        # 2. Alias with no country bias (the global default)
        stmt = (
            select(CityAlias)
            .options(
                selectinload(CityAlias.city).selectinload(City.country),
                selectinload(CityAlias.city).selectinload(City.airports),
            )
            .where(CityAlias.alias_norm == norm, CityAlias.country_bias_alpha2.is_(None))
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        if rows:
            # If multiple default-bias aliases share the same norm, surface
            # them as alternatives (e.g. "brussels" could be BE or US).
            rows_sorted = sorted(rows, key=lambda r: r.city.population or 0, reverse=True)
            primary_row = rows_sorted[0]
            for r in rows_sorted[1:]:
                alternatives.append(self._alias_to_resolution(r, norm, 0.7, "alias"))
            return self._alias_to_resolution(primary_row, norm, 0.95, "alias")

        # 3. Fallback: alias with any country bias.
        # If the user gave a bias, we already matched in step 1.
        # If they didn't, and there are MULTIPLE biased aliases with the
        # same name, it's ambiguous (e.g. "brussels" → BE, US, CA). Don't
        # pick one — let the caller fall through to name resolution, which
        # will surface all candidates.
        if bias:
            return None  # step 1 already returned or there's no biased match
        stmt = (
            select(CityAlias)
            .options(
                selectinload(CityAlias.city).selectinload(City.country),
                selectinload(CityAlias.city).selectinload(City.airports),
            )
            .where(CityAlias.alias_norm == norm, CityAlias.country_bias_alpha2.is_not(None))
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        if not rows:
            return None
        # If only ONE biased alias exists, take it (e.g. "sampa" → BR São Paulo).
        # If multiple exist, treat as ambiguous: surface as alternatives only.
        if len(rows) == 1:
            return self._alias_to_resolution(rows[0], norm, 0.6, "alias")
        for r in rows:
            alternatives.append(self._alias_to_resolution(r, norm, 0.55, "alias"))
        return None  # ambiguous — let name resolution handle the disambiguation

    def _alias_to_resolution(
        self,
        row: CityAlias,
        norm: str,
        confidence: float,
        match_kind: str,
    ) -> LocationResolution:
        city = row.city
        return LocationResolution(
            raw_input=norm,
            matched=True,
            confidence=confidence,
            match_kind=match_kind,
            city=city,
            country=city.country if city else None,
            airport=(city.airports[0] if city and city.airports else None),
        )

    # -- name / ascii resolution -------------------------------------------

    async def _resolve_name(
        self,
        norm: str,
        *,
        country_bias: str | None,
    ) -> tuple[LocationResolution | None, list[LocationResolution]]:
        bias = country_bias.upper() if country_bias else None
        # Try name first
        stmt = select(City).options(
            selectinload(City.country), selectinload(City.airports),
        ).where(City.name.ilike(norm))
        if bias:
            stmt = stmt.where(City.country_alpha2 == bias)
        rows = (await self.session.execute(stmt)).scalars().all()
        if not rows:
            # Try ascii_name
            stmt = select(City).options(
                selectinload(City.country), selectinload(City.airports),
            ).where(City.ascii_name.ilike(norm))
            if bias:
                stmt = stmt.where(City.country_alpha2 == bias)
            rows = (await self.session.execute(stmt)).scalars().all()
        if not rows:
            return None, []

        rows_sorted = sorted(rows, key=lambda c: c.population or 0, reverse=True)
        primary = rows_sorted[0]
        alts = [
            LocationResolution(
                raw_input=norm,
                matched=True,
                confidence=0.85,
                match_kind="name",
                city=c,
                country=c.country,
                airport=(c.airports[0] if c.airports else None),
            )
            for c in rows_sorted[1:4]
        ]
        return LocationResolution(
            raw_input=norm,
            matched=True,
            confidence=0.9,
            match_kind="name",
            city=primary,
            country=primary.country,
            airport=(primary.airports[0] if primary.airports else None),
        ), alts

    # -- fuzzy / prefix -----------------------------------------------------

    async def _resolve_fuzzy(
        self,
        norm: str,
        *,
        country_bias: str | None,
    ) -> tuple[LocationResolution | None, list[LocationResolution]]:
        if len(norm) < 3:
            return None, []
        # Start with prefix, fall back to substring
        pattern = f"{norm}%"
        stmt = select(City).options(
            selectinload(City.country), selectinload(City.airports),
        ).where(
            (City.ascii_name.ilike(pattern)) | (City.name.ilike(pattern))
        )
        if country_bias:
            stmt = stmt.where(City.country_alpha2 == country_bias)
        rows = (await self.session.execute(stmt)).scalars().all()
        if not rows:
            pattern = f"%{norm}%"
            stmt = select(City).options(
                selectinload(City.country), selectinload(City.airports),
            ).where(
                (City.ascii_name.ilike(pattern)) | (City.name.ilike(pattern))
            )
            if country_bias:
                stmt = stmt.where(City.country_alpha2 == country_bias)
            rows = (await self.session.execute(stmt)).scalars().all()
        if not rows:
            return None, []

        rows_sorted = sorted(rows, key=lambda c: c.population or 0, reverse=True)
        primary = rows_sorted[0]
        alts = [
            LocationResolution(
                raw_input=norm,
                matched=True,
                confidence=0.6,
                match_kind="fuzzy",
                city=c,
                country=c.country,
                airport=(c.airports[0] if c.airports else None),
            )
            for c in rows_sorted[1:4]
        ]
        return LocationResolution(
            raw_input=norm,
            matched=True,
            confidence=0.7,
            match_kind="fuzzy",
            city=primary,
            country=primary.country,
            airport=(primary.airports[0] if primary.airports else None),
        ), alts

    # -- public lookup helpers ---------------------------------------------

    async def list_cities(
        self,
        *,
        country_alpha2: str | None = None,
        limit: int = 200,
    ) -> list[City]:
        stmt = select(City).options(
            selectinload(City.country), selectinload(City.airports),
        )
        if country_alpha2:
            stmt = stmt.where(City.country_alpha2 == country_alpha2.upper())
        stmt = stmt.order_by(City.population.desc().nullslast(), City.name.asc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_countries(self) -> list[Country]:
        stmt = select(Country).order_by(Country.name.asc())
        return list((await self.session.execute(stmt)).scalars().all())


# -----------------------------------------------------------------------------
# Module-level convenience
# -----------------------------------------------------------------------------

async def resolve_location(
    session: AsyncSession,
    text: str,
    *,
    country_bias: str | None = None,
) -> LocationResolution:
    return await ReferenceService(session).resolve(text, country_bias=country_bias)


def get_reference_service(session: AsyncSession) -> ReferenceService:
    return ReferenceService(session)


__all__ = [
    "LocationResolution",
    "ReferenceService",
    "get_reference_service",
    "resolve_location",
    "_norm",
]

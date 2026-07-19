"""Reference data: countries, cities, airports, city aliases.

Single source of truth for place names and codes. The frontend fetches
``/api/refdata/cities`` and the backend uses these tables for routing,
disambiguation, and airport lookups (Google Flights IATA codes).

Seeded by SQL on app start (``seed.py``), not via SQLAlchemy defaults,
so it can be re-seeded or extended without a schema migration.
"""
from app.refdata.models import Airport, City, CityAlias, Country
from app.refdata.service import (
    LocationResolution,
    ReferenceService,
    get_reference_service,
    resolve_location,
)

__all__ = [
    "Airport",
    "City",
    "CityAlias",
    "Country",
    "LocationResolution",
    "ReferenceService",
    "get_reference_service",
    "resolve_location",
]

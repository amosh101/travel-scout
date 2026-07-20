"""ISO-compliant location schema.

Every place on Earth referenced by the system is represented as a
``Location`` object carrying the canonical ISO codes:

* **ISO 3166-1** (country)
  - ``country_alpha2``  e.g. ``"MZ"``
  - ``country_alpha3``  e.g. ``"MOZ"``
  - ``country_numeric`` e.g. ``"508"`` (3-digit, zero-padded)
  - ``country_name_en`` e.g. ``"Mozambique"``
* **ISO 3166-2** (country subdivision / state / province)
  - ``subdivision_code`` e.g. ``"MZ-MPM"`` (Maputo City)
  - ``subdivision_name`` e.g. ``"Maputo City"``
* **ISO 6709** (coordinate, WGS84 datum)
  - ``latitude``  decimal degrees
  - ``longitude`` decimal degrees
* **UN M49** (macro-geographic region)
  - ``region_code`` e.g. ``"002"`` = Africa
  - ``region_name`` e.g. ``"Africa"``
* **Wikidata** (cross-source identifier)
  - ``wikidata_qid`` e.g. ``"Q1029"`` (Mozambique)
  - ``wikidata_city_qid`` e.g. ``"Q3889"`` (Maputo)
* **GeoNames** (cross-source identifier)
  - ``geonames_id``  e.g. ``1038906`` (Maputo)
  - ``geonames_feature_code`` e.g. ``"PPLC"`` (capital of country)
* **Display**
  - ``locality``  city / town / place name as user typed
  - ``display_name``  full hierarchical string (e.g. "Maputo, MZ")
* **Provenance / quality**
  - ``sources``  list of contributing source keys (nominatim, geonames,
    restcountries, wikidata, mledoze)
  - ``confidence``  0.0..1.0 — fraction of sources that agree
  - ``resolved_at``  ISO timestamp of last resolution
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass
class GeoSource:
    """One observation of a place from a single upstream source."""
    source: str                # "nominatim" | "geonames" | "restcountries" | "wikidata" | "mledoze"
    country_alpha2: str = ""   # observed
    country_alpha3: str = ""   # observed
    country_numeric: str = ""  # observed
    subdivision_code: str = "" # observed
    locality: str = ""         # observed
    latitude: float | None = None
    longitude: float | None = None
    wikidata_qid: str = ""     # country QID observed
    geonames_id: int | None = None
    feature_code: str = ""     # e.g. "PPLC", "PPLA", "ADM1"
    matched: bool = True       # did this source agree with the consensus?


@dataclass
class Location:
    """ISO-compliant place reference, cross-validated by multiple sources."""
    country_alpha2: str = ""
    country_alpha3: str = ""
    country_numeric: str = ""
    country_name_en: str = ""
    subdivision_code: str = ""
    subdivision_name: str = ""
    locality: str = ""
    display_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    wikidata_qid: str = ""           # country
    wikidata_city_qid: str = ""      # city
    geonames_id: int | None = None
    geonames_feature_code: str = ""
    region_code: str = ""            # UN M49
    region_name: str = ""
    sources: list[GeoSource] = field(default_factory=list)
    confidence: float = 0.0
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [asdict(s) for s in self.sources]
        return d

    @classmethod
    def now(cls, **kwargs: Any) -> "Location":
        kwargs.setdefault("resolved_at", datetime.now(timezone.utc).isoformat())
        return cls(**kwargs)

    @property
    def has_country(self) -> bool:
        return bool(self.country_alpha2) and len(self.country_alpha2) == 2

    @property
    def is_iso_clean(self) -> bool:
        """True if all the standard country fields are populated and consistent."""
        return (
            bool(self.country_alpha2)
            and bool(self.country_alpha3)
            and bool(self.country_numeric)
            and bool(self.country_name_en)
        )

    def to_iso6709(self) -> str:
        """Return the location as an ISO 6709 coordinate string.

        Format: ``+DD.dddd+DDD.dddd/`` (lat,lon, trailing slash is the
        end-of-coordinate marker per the spec). Returns empty string
        if coordinates are missing.
        """
        if self.latitude is None or self.longitude is None:
            return ""
        return f"{self.latitude:+.4f}{self.longitude:+.4f}/"


__all__ = ["Location", "GeoSource"]

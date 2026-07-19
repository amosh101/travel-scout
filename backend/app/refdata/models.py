"""ORM models for the reference data (countries, cities, airports, aliases).

Importing the column types lazily avoids a circular import with
``app.models.__init__``, which itself imports from this module.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CHAR,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, relationship

from app.database import Base
from app.models.types import (  # noqa: E402
    PortableUUID,
    created_at_column,
    updated_at_column,
    uuid_pk_column,
)


# -----------------------------------------------------------------------------
# Country
# -----------------------------------------------------------------------------

class Country(Base):
    """ISO 3166-1 country. ``alpha2`` is the canonical join key."""
    __tablename__ = "countries"

    id = uuid_pk_column()
    alpha2 = Column(CHAR(2), nullable=False, unique=True)   # MZ, BE, ZA
    alpha3 = Column(CHAR(3), nullable=False, unique=True)   # MOZ, BEL, ZAF
    name = Column(String(128), nullable=False)              # Mozambique
    name_pt = Column(String(128), nullable=True)            # Moçambique
    currency = Column(CHAR(3), nullable=True)               # MZN
    flag_emoji = Column(CHAR(4), nullable=True)            # 🇲🇿
    languages = Column(String(255), nullable=True)          # pt,en (ISO 639-1)
    region = Column(String(64), nullable=True)              # Africa (ISO 3166-1)
    sub_region = Column(String(64), nullable=True)          # Eastern Africa
    numeric_code = Column(CHAR(3), nullable=True)           # ISO 3166-1 numeric

    created_at = created_at_column()

    cities: Mapped[list["City"]] = relationship(back_populates="country")


# -----------------------------------------------------------------------------
# City
# -----------------------------------------------------------------------------

class City(Base):
    """A city or town. The unit the user thinks in.

    Most cities have one airport; some (London, Paris, New York, São Paulo)
    have many. ``City.airports`` gives the full list, ordered by priority.
    """
    __tablename__ = "cities"

    id = uuid_pk_column()
    name = Column(String(128), nullable=False)              # Cape Town
    ascii_name = Column(String(128), nullable=False)         # ASCII for URL slugs
    country_alpha2 = Column(
        CHAR(2),
        ForeignKey("countries.alpha2", ondelete="RESTRICT"),
        nullable=False,
    )
    region = Column(String(64), nullable=True)              # "Western Cape"
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    timezone = Column(String(64), nullable=True)            # "Africa/Maputo"
    population = Column(Integer, nullable=True)
    is_capital = Column(Boolean, nullable=False, default=False)

    created_at = created_at_column()
    updated_at = updated_at_column()

    country: Mapped[Country] = relationship(back_populates="cities")
    airports: Mapped[list["Airport"]] = relationship(
        back_populates="city",
        order_by="Airport.priority.asc()",
        foreign_keys="Airport.city_id",
    )
    aliases: Mapped[list["CityAlias"]] = relationship(
        back_populates="city",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_cities_country", "country_alpha2"),
        Index("ix_cities_ascii", "ascii_name"),
        UniqueConstraint(
            "country_alpha2", "ascii_name",
            name="uq_cities_country_ascii",
        ),
    )


# -----------------------------------------------------------------------------
# Airport
# -----------------------------------------------------------------------------

class Airport(Base):
    """An airport, heliport, or major rail station.

    IATA is the booking-system key. ICAO is for ATC/aviation. ``priority``
    ranks airports within a city: the one with priority 0 is the default
    for outbound links.
    """
    __tablename__ = "airports"

    id = uuid_pk_column()
    iata = Column(CHAR(3), nullable=True, unique=True)       # MPM, JNB, BRU
    icao = Column(CHAR(4), nullable=True, unique=True)       # FQMA, FAOR, EBBR
    name = Column(String(255), nullable=False)
    short_name = Column(String(128), nullable=True)
    city_id = Column(
        PortableUUID(),
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String(16), nullable=False, default="airport")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    priority = Column(Integer, nullable=False, default=100)
    is_active = Column(Boolean, nullable=False, default=True)

    created_at = created_at_column()
    updated_at = updated_at_column()

    city: Mapped[City] = relationship(
        back_populates="airports",
        foreign_keys=[city_id],
    )

    __table_args__ = (
        Index("ix_airports_city", "city_id"),
        Index("ix_airports_iata", "iata"),
    )


# -----------------------------------------------------------------------------
# City alias
# -----------------------------------------------------------------------------

class CityAlias(Base):
    """A non-canonical name that resolves to a city.

    Examples:
    - "joburg", "jo'burg"        → Johannesburg, ZA
    - "nyc", "the big apple"     → New York, US
    - "mpm"                      → Maputo (airport code used for city)
    - "sao paulo", "sampa"       → São Paulo, BR
    - "brussels" (no country)    → Brussels, BE (most-common fallback)
    """
    __tablename__ = "city_aliases"

    id = uuid_pk_column()
    city_id = Column(
        PortableUUID(),
        ForeignKey("cities.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias = Column(String(128), nullable=False)
    alias_norm = Column(String(128), nullable=False)
    alias_kind = Column(String(16), nullable=False, default="local")
    country_bias_alpha2 = Column(CHAR(2), nullable=True)

    city: Mapped[City] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("alias_norm", "country_bias_alpha2", name="uq_alias_norm_country"),
        Index("ix_aliases_norm", "alias_norm"),
    )


__all__ = ["Airport", "City", "CityAlias", "Country"]

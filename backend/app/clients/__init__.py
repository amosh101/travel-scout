"""Public re-exports for the clients package.

Free / public (no key needed):
  - jolpica      F1 race calendar
  - nominatim    OSM geocoding
  - overpass     OSM POI search (hotels, attractions)
  - osrm         OSRM routing
  - holidays     Nager.Date public holidays

Require API key (raise NotConfiguredError if called without key):
  - kiwi         flight search
  - ticketmaster events search
"""
from app.clients.base import BaseClient, NotConfiguredError, require_configured
from app.clients.jolpica import JolpicaClient, JolpicaRace, build_jolpica_client
from app.clients.nominatim import (
    GeocodeResult,
    NominatimClient,
    build_nominatim_client,
)
from app.clients.overpass import OverpassClient, POI, build_overpass_client
from app.clients.osrm import OSRMClient, Route, build_osrm_client
from app.clients.holidays import (
    HolidaysClient,
    PublicHoliday,
    SADC_COUNTRY_CODES,
    build_holidays_client,
)
from app.clients.kiwi import KiwiClient, KiwiFlightOffer, build_kiwi_client
from app.clients.ticketmaster import (
    TicketmasterClient,
    TicketmasterEvent,
    build_ticketmaster_client,
)

__all__ = [
    # base
    "BaseClient",
    "NotConfiguredError",
    "require_configured",
    # free / public
    "JolpicaClient",
    "JolpicaRace",
    "build_jolpica_client",
    "NominatimClient",
    "GeocodeResult",
    "build_nominatim_client",
    "OverpassClient",
    "POI",
    "build_overpass_client",
    "OSRMClient",
    "Route",
    "build_osrm_client",
    "HolidaysClient",
    "PublicHoliday",
    "SADC_COUNTRY_CODES",
    "build_holidays_client",
    # require key
    "KiwiClient",
    "KiwiFlightOffer",
    "build_kiwi_client",
    "TicketmasterClient",
    "TicketmasterEvent",
    "build_ticketmaster_client",
]

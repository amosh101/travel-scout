"""Pydantic-style data schemas for the travel-scout service.

Currently just re-exports the Location dataclass from app.schemas.location.
"""
from app.schemas.location import Location, GeoSource

__all__ = ["Location", "GeoSource"]

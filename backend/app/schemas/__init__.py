"""Schemas subpackage (split from the historical single-file schemas.py).

Currently a re-export hub for the schema pieces of major features.

NB: this ``__init__`` may double-expose schema classes (Location,
GeoSource, plus the messaging/me/itineraries schemas imported below).
Importers should do ``from app.schemas import X`` rather than reaching
into submodule paths — that way the public surface stays stable when
files migrate.

Specific re-exports (2026-07-24):
  - app.schemas.location: Location, GeoSource (T7 ISO 3166)
  - app.schemas.messages: MessageOut, AttachmentOut, PostMessageIn,
    MessageList, HandOffBrief (T8e chat)
"""
from app.schemas.location import Location, GeoSource
from app.schemas.messages import (  # noqa: F401
    AttachmentOut,
    HandOffBrief,
    MessageList,
    MessageOut,
    PostMessageIn,
)

__all__ = [
    "Location",
    "GeoSource",
    "MessageOut",
    "AttachmentOut",
    "PostMessageIn",
    "MessageList",
    "HandOffBrief",
] 

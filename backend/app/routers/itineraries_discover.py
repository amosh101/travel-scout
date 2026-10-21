"""Itineraries discovery router.

Authenticated entry point for the new user journey. Loads the user's
stored interests and runs the intersection algorithm.

GET /api/itineraries/discover
    Returns ranked itineraries based on the user's stored interests
    plus optional overrides (``origin``, ``date_from``, ``date_to``,
    ``destinations``).

The body of the work reuses the search router's ``_score_itinerary`` and
the discover router's country disambiguation table. We do NOT call the
discover router directly (FastAPI doesn't let us call a route handler
from inside another route easily); we call the underlying clients
directly. This keeps the response shape stable for the frontend.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import (
    build_holidays_client,
    build_jolpica_client,
    build_nominatim_client,
    build_osrm_client,
    build_overpass_client,
)
from app.clients.location_resolver import build_location_resolver
from app.refdata.iso3166 import resolve_alpha2 as _resolve_country_alpha2
from app.database import get_session
from app.models import (
    ActorKind,
    AuditLog,
    Interest,
    User,
    UserInterest,
)
from app.routers.auth import get_current_user, get_optional_user
from app.routers.search import Itinerary, _build_pitch, _score_itinerary
from app.routers.discover import (
    _COUNTRY_NAME_TO_CODE,
)
from app.services.audit import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/itineraries", tags=["itineraries-discover"])


# -----------------------------------------------------------------------------
# Helper: load the user's stored interests
# -----------------------------------------------------------------------------

async def _load_user_interests(
    session: AsyncSession, user_id
) -> list[dict[str, Any]]:
    """Return ``[{key, name}]`` for the user's stored interests."""
    rows = (
        await session.execute(
            select(UserInterest).where(UserInterest.user_id == user_id)
        )
    ).scalars().all()
    if not rows:
        return []
    interest_ids = [r.interest_id for r in rows]
    interests = (
        await session.execute(select(Interest).where(Interest.id.in_(interest_ids)))
    ).scalars().all()
    meta_by_id = {i.id: i for i in interests}
    out: list[dict[str, Any]] = []
    for r in rows:
        meta = meta_by_id.get(r.interest_id)
        if meta is None:
            continue
        out.append({"key": meta.key, "name": meta.name})
    return out


async def _load_user_profile_intake(
    session: AsyncSession, user: User
) -> dict[str, Any] | None:
    """Try to recover the most-recent intake from the audit log.

    We don't have a dedicated profile_answers column on User yet; the
    intake values are recorded in the ``user.register`` audit row's
    ``metadata`` blob. This is the closest we have for "the user's
    landing-page answers" in v2.1.
    """
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.actor_user_id == user.id,
            AuditLog.action.in_(("user.register", "user.intake_updated")),
        )
        .order_by(AuditLog.at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    md = row.metadata_json or {}
    if not md.get("has_intake"):
        return None
    return {
        "origin": md.get("origin") or "Maputo",
        "destinations": md.get("destinations") or [],
        # New: the time-window enum. Old intakes predate the enum and
        # won't have it; we default to ``year`` (next 6 months) which
        # is the closest match to the old "no dates" behaviour.
        "when": md.get("when") or "year",
        "when_label": md.get("when_label") or "next 6 months",
        # Backwards-compat.
        "travel_soon": bool(md.get("travel_soon")),
        "date_from": md.get("date_from"),
        "date_to": md.get("date_to"),
    }


# -----------------------------------------------------------------------------
# Helper: build an itinerary for one candidate destination
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Event-window helper (T8a)
# -----------------------------------------------------------------------------
#
# Per the v2 brief: each anchor event (F1 race, public holiday) defines its
# own trip window. The window is ``[event_start - 2d, event_end + 2d]`` so a
# 3-day F1 weekend becomes a 7-day trip. For single-day events (holidays),
# the window is 5 days centred on the event date.
#
# The result itinerary's date range is THIS window, not the user's
# 6-month profile window — the user sees concrete dates they can save.
# The 2-week cap is enforced separately (T8b).

EVENT_PADDING_DAYS = 2  # before/after the anchor event
MAX_ITINERARY_DAYS = 14  # hard cap (T8b)


def compute_event_window(
    event_start: date,
    event_end: date | None = None,
    pad: int = EVENT_PADDING_DAYS,
) -> tuple[date, date]:
    """Return the per-event window: ``[event_start - pad, event_end + pad]``.

    For single-day events, ``event_end`` defaults to ``event_start``.
    """
    end = event_end or event_start
    return (event_start - timedelta(days=pad), end + timedelta(days=pad))


async def _build_itinerary_for(
    session: AsyncSession,
    *,
    candidate_name: str,
    candidate_country_hint: str | None,
    origin_geo,
    origin_resolution: dict | None,
    date_from: date,
    date_to: date,
    interests: list[str],
    season_races: list,
    holidays_client,
    osrm,
    nomi,
    overpass,
    sources_used: list[str],
    is_anonymous: bool = False,
) -> tuple[Itinerary | None, dict | None]:
    """Run the full intersection for one destination.

    Resolution priority:
    1. ReferenceService (canonical city, IATA, lat/lon)
    2. Nominatim fallback (for unknown places)
    """
    from app.refdata.service import ReferenceService
    ref = ReferenceService(session)

    # 1. Try ReferenceService first
    res = await ref.resolve(candidate_name, country_bias=candidate_country_hint)
    res_d = res.to_dict()
    use_nomi = False
    if res_d["matched"] and res_d["city"]:
        sources_used.append("refdata")
        d_country = res_d["country"]["alpha2"]
        d_lat = res_d["city"]["latitude"]
        d_lon = res_d["city"]["longitude"]
        d_name = res_d["city"]["name"]
        d_country_name = res_d["country"]["name"]
        # CROSS-CHECK: if refdata surfaced alternatives (e.g. Paris
        # could be FR, US, or CA), validate against the LocationResolver
        # consensus (Nominatim + Wikidata + ISO 3166-1). The resolver
        # uses Wikidata's "largest city wins" heuristic via SPARQL
        # ORDER BY DESC(population), so the famous city wins.
        has_alternatives = bool(res.alternatives)
        hint_disagrees = (
            candidate_country_hint
            and d_country != candidate_country_hint.upper()
        )
        # Always cross-check when no country hint was given — the
        # refdata DB may have a single alias for a famous city
        # (Paris -> US Texas) and we need the resolver consensus to
        # pick the right one. The resolver is fast (~200ms cached)
        # so this is cheap.
        no_hint = not candidate_country_hint
        if has_alternatives or hint_disagrees or no_hint:
            try:
                resolver = build_location_resolver()
                # IMPORTANT: when no country hint was given, pass
                # None to the resolver so it consensus-validates
                # without bias. If we passed d_country (the refdata
                # pick) as a hint, the resolver would just confirm
                # the wrong pick. When a hint IS given, pass it so
                # the resolver can confirm or override.
                cross_cc = (
                    candidate_country_hint.upper()
                    if candidate_country_hint
                    else None
                )
                loc = await resolver.resolve(candidate_name, cross_cc, timeout=4.0)
                # Sanity: if the resolver returned a *different*
                # country with a confident consensus, swap. If the
                # user gave a hint and the resolver agreed, we keep
                # the refdata pick (or overwrite, since they're the
                # same anyway). If the resolver returned the same
                # country as refdata, no-op.
                if (
                    loc.has_country
                    and loc.country_alpha2 != d_country
                    and loc.latitude is not None
                    and loc.confidence >= 0.5
                ):
                    logger.info(
                        "Disambiguated %r: refdata=%s -> resolver=%s (%.0f%% confidence)",
                        candidate_name, d_country, loc.country_alpha2,
                        loc.confidence * 100,
                    )
                    d_country = loc.country_alpha2
                    d_country_name = loc.country_name_en
                    if loc.locality:
                        d_name = loc.locality
                    if loc.latitude is not None:
                        d_lat = loc.latitude
                    if loc.longitude is not None:
                        d_lon = loc.longitude
                    sources_used.append("location_resolver")
            except Exception as e:  # noqa: BLE001
                logger.debug("LocationResolver cross-check failed: %s", e)
    else:
        # 2. Fall back to Nominatim, then cross-validate with the
        # LocationResolver (Nominatim + Wikidata SPARQL + bundled ISO
        # 3166-1). This is the fix for "Paris" -> Texas: if the user
        # typed a famous city name that has multiple matches, the
        # resolver picks the most populous one (Paris-FR > Paris-TX).
        q = candidate_name
        if candidate_country_hint and "," not in q:
            q = f"{q}, {candidate_country_hint}"
        try:
            results = await nomi.geocode(q, limit=5)
        except Exception as e:  # noqa: BLE001
            logger.warning("Nominatim failed for %s: %s", q, e)
            results = []
        if not results:
            return None, None
        # Pick the most important result unless we have a country hint
        # that disagrees — in which case try the resolver instead.
        if candidate_country_hint:
            best = None
            for r in results:
                if (r.country_code or "").upper() == candidate_country_hint.upper():
                    best = r
                    break
            if best is None:
                best = max(results, key=lambda r: float(r.importance or 0))
        else:
            best = max(results, key=lambda r: float(r.importance or 0))
        if "nominatim" not in sources_used:
            sources_used.append("nominatim")
        d_country = (best.country_code or "").upper() or (candidate_country_hint or "").upper()
        d_lat = best.lat
        d_lon = best.lon
        d_name = best.display_name.split(",")[0].strip()
        d_country_name = best.display_name.split(",")[-1].strip()
        # If a country hint was given and doesn't match, try the
        # LocationResolver to find the right one. This catches cases
        # where Nominatim returns a low-importance match (e.g. Paris,
        # Texas) over the famous one (Paris, France) when the user
        # didn't provide a hint.
        if candidate_country_hint and d_country != candidate_country_hint.upper():
            try:
                resolver = build_location_resolver()
                loc = await resolver.resolve(candidate_name, candidate_country_hint.upper())
                if loc.has_country and loc.country_alpha2 == candidate_country_hint.upper():
                    # Overwrite with the resolver's pick
                    d_country = loc.country_alpha2
                    d_country_name = loc.country_name_en
                    if loc.locality:
                        d_name = loc.locality
                    if loc.latitude is not None:
                        d_lat = loc.latitude
                    if loc.longitude is not None:
                        d_lon = loc.longitude
                    sources_used.append("location_resolver")
            except Exception as e:  # noqa: BLE001
                logger.debug("LocationResolver cross-check failed: %s", e)

    duration = (date_to - date_from).days + 1
    route = None
    if origin_geo is not None:
        try:
            route = await osrm.route(origin_geo.lon, origin_geo.lat, d_lon, d_lat)
        except Exception as e:  # noqa: BLE001
            logger.warning("OSRM route failed: %s", e)
    if route and "osrm" not in sources_used:
        sources_used.append("osrm")

    # F1 races at this destination (within the user's profile window).
    # The first one will be the anchor for the event window (T8a).
    races_at: list[dict] = []
    # T8d: per-suggestion booking link.
    race_url = "https://www.formula1.com/en/racing/2026"
    for r in season_races:
        race_cc = _COUNTRY_NAME_TO_CODE.get(r.country.upper(), "")
        if race_cc and d_country and race_cc == d_country:
            # Strict window — the race must start inside the user's
            # profile window. The per-event window (T8a: race ± 2 days)
            # is applied downstream to size the trip, not here.
            if date_from <= r.starts_at.date() <= date_to:
                races_at.append({
                    "name": r.name,
                    "circuit": r.circuit,
                    "city": r.city,
                    "country": r.country,
                    "starts_at": r.starts_at.isoformat(),
                    "ends_at": r.ends_at.isoformat() if r.ends_at else None,
                    "source": "jolpica",
                    "source_url": race_url,
                    "booking_link": race_url,
                    "booking_label": "View on Formula1.com",
                })
    if races_at and "jolpica" not in sources_used:
        sources_used.append("jolpica")

    # Public holidays for this country. We only filter to the EVENT window
    # below (not the user's profile window) so a 6-month profile window
    # cannot leak holidays that fall outside the actual trip dates. We
    # drop anything older than date_from here so a 2026 query doesn't
    # pull December 2025 leftovers, and anything beyond date_to (caller
    # will tighten to event window once we know it).
    holiday_alerts: list[dict] = []
    if d_country:
        try:
            hs = await holidays_client.fetch_year(date_from.year, d_country)
        except Exception as e:  # noqa: BLE001
            logger.warning("Holidays failed for %s: %s", d_country, e)
            hs = []
        for h in hs:
            try:
                hd = date.fromisoformat(h.date)
            except ValueError:
                continue
            if hd < date_from:
                continue
            holiday_alerts.append({
                "date": h.date,
                "name": h.english_name,
                "local": h.local_name,
                "source": "nager.date",
                "booking_link": (
                    f"https://date.nager.at/PublicHoliday/{d_country.lower()}"
                    f"/{date_from.year}"
                ),
            })
        if holiday_alerts and "nager.date" not in sources_used:
            sources_used.append("nager.date")

    # ------------------------------------------------------------------
    # T8a: derive the per-event window from the first anchor event.
    # - F1 race weekend: [race.starts_at - 2d, race.ends_at + 2d]
    # - Public holiday:  [holiday - 2d, holiday + 2d]
    # - No anchor:        keep the user's profile window
    # ------------------------------------------------------------------
    event_window_meta: dict | None = None
    if races_at:
        anchor = races_at[0]
        anchor_start = date.fromisoformat(anchor["starts_at"][:10])
        anchor_end = (
            date.fromisoformat(anchor["ends_at"][:10])
            if anchor.get("ends_at")
            else anchor_start
        )
        win_from, win_to = compute_event_window(anchor_start, anchor_end)
        event_window_meta = {
            "kind": "f1_race",
            "anchor_name": anchor["name"],
            "anchor_start": anchor["starts_at"][:10],
            "anchor_end": (anchor.get("ends_at") or anchor["starts_at"])[:10],
            "window_start": win_from.isoformat(),
            "window_end": win_to.isoformat(),
        }
    elif holiday_alerts:
        # T8a fix: DON'T auto-anchor on the first holiday for non-F1
        # trips. The user's window is wide (e.g. next 6 months); the
        # holiday-anchor logic is for F1 weekend trips, not for
        # "what's happening in this city in my window" queries. Keep
        # ``event_window_meta = None`` so the result uses the full
        # profile window.
        pass

    # T8c: holidays are filtered to the event window (or the profile
    # window if no anchor event was found). The loop above already
    # filtered to the profile window; re-filter to the event window now
    # that we have it.
    #
    # Disable the narrow filter for now: for any non-trivial query
    # (e.g. "Sao Paulo next 6 months" with 1 F1 race + 6 holidays), the
    # narrow event window strips the holidays that don't fall in the
    # race's 5-day weekend, leaving the user with an itinerary that
    # says "this trip has 1 race and 0 holidays" when in fact there
    # are 6 holidays in their trip horizon. Returning all events in
    # the profile window is the honest, user-aligned behaviour.
    if False and (
        event_window_meta is not None
        and event_window_meta.get("kind") == "f1_race"
        and len(races_at) == 1
    ):
        win_from = date.fromisoformat(event_window_meta["window_start"])
        win_to = date.fromisoformat(event_window_meta["window_end"])
        races_at = [
            r for r in races_at
            if win_from <= date.fromisoformat(r["starts_at"][:10]) <= win_to
        ]
        holiday_alerts = [
            h for h in holiday_alerts
            if win_from <= date.fromisoformat(h["date"]) <= win_to
        ]

    # If we have an event window, use it as the itinerary dates.
    if event_window_meta is not None:
        it_start = date.fromisoformat(event_window_meta["window_start"])
        it_end = date.fromisoformat(event_window_meta["window_end"])
    else:
        it_start = date_from
        it_end = date_to
    duration = (it_end - it_start).days + 1

    # T8b: enforce 14-day hard cap. Beyond that, the user is planning
    # something else, not a trip-around-an-event. Drop with a warning so
    # the caller can see why.
    # T8b: enforce 14-day hard cap on EVENT-WINDOW trips. Beyond that,
    # the user is planning something else, not a trip-around-an-event.
    # Trips without an event anchor (e.g. Bangkok, no F1 race) keep
    # the user's full date range so we don't drop the only candidate
    # they care about.
    if event_window_meta is not None and duration > MAX_ITINERARY_DAYS:
        logger.info(
            "Dropping itinerary for %s: event window %s..%s (%d days) exceeds cap",
            candidate_name, it_start, it_end, duration,
        )
        return None, None

    # T8b: intersection rule. A useful trip needs the anchor event + at
    # least 1 more activity in the same window. Today the only "other
    # activity" data source is public holidays; when hotels are wired in,
    # they count too.
    extra_activities = len(holiday_alerts)
    if races_at and extra_activities == 0:
        logger.info(
            "Dropping itinerary for %s: race anchor but no other activities in window",
            candidate_name,
        )
        return None, None

    # If we have an event window, use it as the itinerary dates.
    # an F1-related interest, an F1 race at this destination is the
    # anchor.
    f1_kw = {"f1", "f1 / motorsport", "motorsport", "formula 1", "racing"}
    interests_norm = {i.strip().lower() for i in interests if i}
    is_f1_trip = bool(interests_norm & f1_kw)

    # Default interest set for anonymous / unset interest queries.
    # The free-events aggregator (Wikidata + Wikipedia) returns good
    # coverage on these six across most countries. Falls through to
    # the existing logic so the user's stored interests still win
    # when they exist.
    if not interests_norm:
        interests_norm = {
            "modern-art", "football", "cycling", "jazz",
            "opera", "design",
        }

    anchor_events: list[dict] = []
    for race in races_at:
        # T8d: booking link is already attached to each race by the
        # builder above; we just pass it through.
        anchor_events.append({
            "kind": "f1_race",
            "title": race["name"],
            "date": race["starts_at"],
            "date_end": race.get("ends_at"),
            "city": race["city"],
            "country": race["country"],
            "circuit": race["circuit"],
            "source": "jolpica",
            "source_url": race.get("source_url"),
            "booking_link": race.get("booking_link"),
            "booking_label": race.get("booking_label"),
        })
    for h in holiday_alerts:
        # T8d: Nager.Date country page lists every public holiday for
        # the year with a small description — useful for the user to
        # understand what the local celebration is.
        holiday_url = (
            f"https://date.nager.at/PublicHoliday/{d_country.lower()}"
            f"/{date_from.year}"
        )
        anchor_events.append({
            "kind": "public_holiday",
            "title": h["name"],
            "local": h["local"],
            "date": h["date"],
            "source": "nager.date",
            "source_url": holiday_url,
            "booking_link": holiday_url,
            "booking_label": "View on Nager.Date",
        })

    # Free event sources — Wikidata + Wikipedia. For each user
    # interest, fetch the matching free events and append the ones
    # that fall in the trip window. This is where the "interest
    # driven" promise of the PRD actually gets fulfilled: jazz,
    # classical, electronic, rock, cycling, sport, art-museums,
    # architecture, design, photography, literature, food-wine,
    # adventure, motorsport all have free sources now.
    from app.clients.free_events import build_free_event_aggregator
    free_agg = build_free_event_aggregator()
    non_anchor_interests = [i for i in interests_norm
                             if i not in f1_kw and i != "public-holidays"]
    # Free event sources (Wikidata + Wikipedia) are rate-limited and
    # only fire when the user has STORED interests. The default set
    # used for anonymous previews doesn't query the free sources —
    # they get race + holidays + hotels instead. A user with stored
    # interests gets their personalised events from the curated
    # Wikidata/Wikipedia lists on top of the basic result.
    if non_anchor_interests and not is_anonymous:
        from app.clients.free_events import _FREE_EVENTS_CACHE

        # Bound the number of concurrent Wikipedia + Wikidata calls
        # to 2 — their per-IP rate limits degrade badly when we hit
        # them in parallel, and we want at least one of the queries
        # to succeed rather than all of them time out.
        sem = asyncio.Semaphore(2)

        async def _search_with_cap(interest: str):
            cache_key = (interest, d_country or "", candidate_name.lower())
            cached = _FREE_EVENTS_CACHE.get(cache_key)
            if cached is not None:
                return cached
            try:
                # 6s per interest — gives Wikidata + Wikipedia enough
                # time to answer even when their rate limit is briefly
                # throttling us. The cache makes this a one-time cost
                # per (interest, country, city) tuple.
                async with sem:
                    result = await asyncio.wait_for(
                        free_agg.search(
                            interest_key=interest,
                            country_alpha2=d_country,
                            start_date=date_from,
                            end_date=date_to,
                            city=candidate_name,
                            limit=5,
                        ),
                        timeout=6.0,
                    )
                _FREE_EVENTS_CACHE[cache_key] = result
                return result
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                logger.info("Free events for %s in %s: %s", interest, candidate_name, e)
                _FREE_EVENTS_CACHE[cache_key] = []
                return []

        try:
            per_interest = await asyncio.gather(
                *(_search_with_cap(k) for k in non_anchor_interests),
                return_exceptions=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Free event aggregator failed: %s", e)
            per_interest = []
        for batch in per_interest:
            if isinstance(batch, Exception):
                logger.warning("Free event search failed: %s", batch)
                continue
            for e in batch:
                # ``e`` is an ``EventRecord`` dataclass (or a dict if
                # a source returned one — handle both). Use getattr
                # for the dataclass path, .get() for the dict path.
                if isinstance(e, dict):
                    kind = e.get("kind", "event")
                    title = e.get("name", "Event")
                    starts_at = e.get("starts_at")
                    city = e.get("city", "")
                    country = e.get("country", "")
                    source = e.get("source", "wikipedia")
                    source_url = e.get("source_url")
                else:
                    kind = getattr(e, "kind", "event") or "event"
                    title = getattr(e, "name", None) or "Event"
                    starts_at = getattr(e, "starts_at", None)
                    city = getattr(e, "city", "") or ""
                    country = getattr(e, "country", "") or ""
                    source = getattr(e, "source", "") or "wikipedia"
                    source_url = getattr(e, "source_url", None)
                anchor_events.append({
                    "kind": kind,
                    "title": title,
                    "date": starts_at.isoformat() if starts_at else None,
                    "city": city,
                    "country": country,
                    "source": source,
                    "source_url": source_url,
                })
        if per_interest and "free_events" not in sources_used:
            sources_used.append("free_events")

    # Hotels via OpenStreetMap Overpass. Free, no key, real data.
    # 5km radius for downtown. Failures return [] and the result
    # simply omits the section — never fabricated. We do NOT retry
    # at a wider radius (was causing 2x the latency); 5km is the
    # right scale for downtown and the OSM coverage in 10km of
    # the same point is almost always the same set of hotels.
    hotels: list[dict] = []
    if d_lat and d_lon and overpass is not None:
        try:
            hotel_pois = await overpass.search_hotels_near(
                d_lat, d_lon, radius_km=5.0, limit=15,
            )
            hotels = [
                {
                    "osm_id": p.osm_id,
                    "name": p.name,
                    "lat": p.lat,
                    "lon": p.lon,
                    "stars": p.tags.get("stars") or p.tags.get("stars:official"),
                    "rooms": p.tags.get("rooms") or p.tags.get("capacity"),
                    "addr": p.tags.get("addr:full") or (
                        ", ".join(filter(None, [
                            p.tags.get("addr:street"),
                            p.tags.get("addr:housenumber"),
                        ])) or None
                    ),
                    "phone": p.tags.get("phone") or p.tags.get("contact:phone"),
                    "website": p.tags.get("website") or p.tags.get("contact:website"),
                    "wikidata": p.tags.get("wikidata"),
                    "wikipedia": p.tags.get("wikipedia"),
                }
                for p in hotel_pois
            ]
            if hotels and "overpass" not in sources_used:
                sources_used.append("overpass")
        except Exception as e:  # noqa: BLE001
            logger.warning("Overpass hotel search failed: %s", e)
            hotels = []

    # Score (audit-only reasons) + user-facing pitch.
    score, audit_reasons = _score_itinerary(
        distance_km=(route.distance_m / 1000) if route else 0.0,
        duration_days=duration,
        races_at_destination=len(races_at),
        holidays_count=len(holiday_alerts),
    )
    pitch = _build_pitch(
        interests=interests,
        races_in_window=races_at,
        holiday_alerts=holiday_alerts,
        duration_days=duration,
        has_event_window=event_window_meta is not None,
    )

    # Derive a clean display: use the country_code (e.g. "BE") if available,
    # else fall back to the last segment of the display name. The raw
    # display name for "Spa" is "Spa, België / Belgique / Belgien" which
    # is ugly in the UI.
    country_label = d_country_name if d_country_name else (d_country or "")
    logger.info(
        "itinerary %s: score=%s reasons=%s pitch=%s",
        candidate_name, score, audit_reasons, pitch,
    )
    return Itinerary(
        rank=0,
        score=round(score, 1),
        pitch=pitch,
        destination=d_name,
        destination_country=country_label,
        destination_country_code=d_country or None,
        start_date=it_start.isoformat(),
        end_date=it_end.isoformat(),
        duration_days=duration,
        total_distance_km=(route.distance_m / 1000) if route else 0.0,
        races_in_window=races_at,
        holiday_alerts=holiday_alerts,
        # Wikidata + Wikipedia events for the user's interests (or the
        # default interest set if none were given). Each event is a
        # dict with kind/title/date/city/country/source/source_url —
        # the front-end renders them in the "events in this trip" list.
        interest_events=anchor_events,
        hotels=hotels,
        route={
            "distance_km": route.distance_m / 1000,
            # T8b: drive-time removed from results. We keep distance for
            # context ("this is a long-haul trip") but no longer imply
            # driving is the suggested transport.
        } if route else None,
        sources=list(set(sources_used)),
        missing=[],
        # event_window and per-suggestion links are added by the route
        # handler in the rich envelope below (the dataclass is shared
        # with the search router).
    ), event_window_meta


# Convenience wrapper used elsewhere; returns just the Itinerary.
async def _build_itinerary_only(
    session: AsyncSession,
    **kwargs,
) -> Itinerary | None:
    it, _ = await _build_itinerary_for(session, **kwargs)
    return it


async def _season_races_for_window(jolpica, date_from: date, date_to: date) -> list:
    """Jolpica season entries covering the window, year-straddle safe.

    ``fetch_season`` is called per year so a window that crosses a
    season boundary (e.g. "next 6 months" from October reaches into
    the following March) still sees the next season's races. Entries
    are de-duplicated by (city, country, start date).
    """
    races: list = []
    for y in sorted({date_from.year, date_to.year}):
        try:
            races.extend(await jolpica.fetch_season(y))
        except Exception as e:  # noqa: BLE001
            logger.warning("Jolpica season %s fetch failed: %s", y, e)
    seen: set[tuple] = set()
    out: list = []
    for r in races:
        k = (r.city, r.country, r.starts_at)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.get("/discover")
async def discover(
    user: Annotated[User | None, Depends(get_optional_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    origin: str | None = Query(None, description="Override the user's origin"),
    destination: str | None = Query(None, description="Override candidate destinations"),
    interests: str | None = Query(
        None,
        description=(
            "Comma-separated interest names for the interest-driven "
            "anonymous preview. For signed-in users this is honoured "
            "only when their stored profile has no interests."
        ),
    ),
    interest: str | None = Query(
        None,
        description="Singular alias of ``interests`` (single name).",
    ),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    top_n: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Ranked itineraries.

    Works for both authenticated and anonymous users:

    - **Signed in:** uses the user's stored interests, intake window,
      and origins. The original behaviour.
    - **Anonymous:** either ``?destination=City&date_from=...&date_to=...``
      (destination preview), or ``?interest=Name&...`` for an
      event-anchored preview built from real events in the window.
      Used for the "preview before signup" flow.

    Both branches return the same shape so the frontend renders results
    identically; only the save buttons differ (auth required for save).
    """
    if user is not None:
        return await _discover_for_user(
            session, user, origin, destination,
            interests_param=interests or interest,
            date_from=date_from, date_to=date_to, top_n=top_n,
        )
    return await _discover_anonymous(
        session, origin, destination,
        interests_param=interests or interest,
        date_from=date_from, date_to=date_to, top_n=top_n,
    )


async def _discover_for_user(
    session: AsyncSession,
    user: User,
    origin: str | None,
    destination: str | None,
    interests_param: str | None,
    date_from: date | None,
    date_to: date | None,
    top_n: int,
) -> dict[str, Any]:
    """Original authenticated flow — uses the user's stored profile."""
    interests = await _load_user_interests(session, user.id)
    # A signed-in user with an EMPTY stored profile can still honour an
    # explicitly passed ?interest= list (e.g. an intake-built deep link)
    # — stored interests always win when they exist.
    if not interests and interests_param:
        interests = [i.strip() for i in interests_param.split(",") if i.strip()]
    # No stored interests is no longer a blocker — the intersection
    # runs with a default interest set (modern-art, football, cycling,
    # jazz, opera, design) that gives broad coverage. The user's
    # profile still drives the date window and origin. We surface
    # the empty profile in the response so the front-end can offer
    # to "add interests" without re-running the search.

    profile = await _load_user_profile_intake(session, user)
    effective_origin = (origin or (profile or {}).get("origin") or "Maputo").strip()

    # ------------------------------------------------------------------
    # Date-window resolution
    # ------------------------------------------------------------------
    # The user picked a ``when`` (now / month / quarter / year / specific)
    # on the landing form. Discover is STRICTLY bounded by that window
    # — we never consider F1 races or holidays that fall outside it.
    # The per-event window (T8a: race ± 2 days) may extend slightly past
    # the profile window because the trip is centred on the event, but
    # the event itself must be inside the profile window.
    from app.services.travel_when import TravelWhen, window_for
    today = date.today()

    # Stored window from the audit log, or the query-param override.
    stored_when_str = (profile or {}).get("when")
    if date_from is None or date_to is None:
        try:
            stored_when = TravelWhen(stored_when_str) if stored_when_str else None
        except ValueError:
            stored_when = None
        if stored_when is not None:
            win_from, win_to = window_for(stored_when, today=today)
        else:
            # Backwards-compat path: dates were stored as raw strings.
            df = (profile or {}).get("date_from")
            dt = (profile or {}).get("date_to")
            try:
                win_from = date.fromisoformat(df) if df else today
            except (TypeError, ValueError):
                win_from = today
            try:
                win_to = date.fromisoformat(dt) if dt else today + timedelta(days=180)
            except (TypeError, ValueError):
                win_to = today + timedelta(days=180)
    else:
        # Explicit query-param override wins.
        win_from = date_from
        win_to = date_to

    if date_from is None:
        date_from = win_from
    if date_to is None:
        date_to = win_to
    if date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")

    # Surface the active window in the response so the front-end can
    # show "Showing trips in your next 3 months (2026-07-17 → 2026-10-17)".
    active_window: dict[str, Any] = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "when": stored_when_str,
        "when_label": (profile or {}).get("when_label"),
    }

    candidates: list[tuple[str, str | None]] = []
    if destination:
        candidates.append((destination.strip(), None))
    else:
        # If the user told us destinations on the landing page, use them.
        for d in (profile or {}).get("destinations") or []:
            if d.strip():
                candidates.append((d.strip(), None))
        # Otherwise seed candidates with every F1 city in the season window.
        # (The landing page is interest-driven; a user who picked F1 gets
        # the season as the candidate pool.) Year-straddle safe: windows
        # crossing a season boundary still see the next season's races.
        jolpica = build_jolpica_client()
        season = await _season_races_for_window(jolpica, date_from, date_to)
        for r in season:
            # Strict window: only F1 races whose start date falls
            # inside the user's profile window are candidate anchors.
            # No ±padding here — that's the event-window concern, not
            # the candidate-pool concern. (See T8a for the ±2 day
            # per-event window used downstream.)
            if date_from <= r.starts_at.date() <= date_to:
                candidates.append((r.city, r.country))
        if not candidates:
            raise HTTPException(
                404,
                "no candidate destinations found. Pass ?destination=City or set dates that include an F1 race.",
            )

    # De-duplicate (case-insensitive).
    seen: set[str] = set()
    deduped: list[tuple[str, str | None]] = []
    for name, hint in candidates:
        k = name.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append((name, hint))
    candidates = deduped[:top_n * 2]  # over-fetch, score-fanout below

    nomi = build_nominatim_client()
    osrm = build_osrm_client()
    jolpica = build_jolpica_client()
    holidays_client = build_holidays_client()
    overpass = build_overpass_client()
    try:
        season_races = await jolpica.fetch_season(date_from.year)
    except Exception:
        season_races = []

    # Resolve origin via ReferenceService first, Nominatim fallback second.
    from app.refdata.service import ReferenceService
    ref = ReferenceService(session)
    origin_res = await ref.resolve(effective_origin)
    origin_res_d = origin_res.to_dict()
    origin_geo_obj = None
    sources_used: list[str] = []
    if origin_res_d["matched"] and origin_res_d["city"]:
        sources_used.append("refdata")
        class _OriginGeo:
            lat = origin_res_d["city"]["latitude"]
            lon = origin_res_d["city"]["longitude"]
            display_name = f"{origin_res_d['city']['name']}, {origin_res_d['country']['name']}"
            country_code = origin_res_d["country"]["alpha2"]
        origin_geo_obj = _OriginGeo()
    else:
        try:
            origin_geo = (await nomi.geocode(effective_origin, limit=1))
        except Exception as e:  # noqa: BLE001
            logger.warning("Origin geocode failed: %s", e)
            origin_geo = []
        origin_geo_obj = origin_geo[0] if origin_geo else None

    built: list[Itinerary] = []
    event_windows_by_dest: dict[str, dict] = {}  # T8a: keyed by destination name
    for cand_name, cand_hint in candidates:
        try:
            it, ew = await _build_itinerary_for(
                session,
                candidate_name=cand_name,
                candidate_country_hint=cand_hint,
                origin_geo=origin_geo_obj,
                origin_resolution=None,  # TODO: wire from caller
                date_from=date_from,
                date_to=date_to,
                interests=[i["key"] for i in interests],
                season_races=season_races,
                holidays_client=holidays_client,
                osrm=osrm,
                nomi=nomi,
                overpass=overpass,
                sources_used=sources_used,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Build itinerary for %s failed: %s", cand_name, e)
            continue
        if it is None:
            continue
        built.append(it)
        if ew is not None:
            event_windows_by_dest[it.destination] = ew

    # Sort and trim
    built.sort(key=lambda i: i.score, reverse=True)
    built = built[:top_n]

    # Enrich each itinerary with IATA codes (origin + destination) from refdata
    # so the saved page can build real flight deep-links without a hardcoded
    # city→IATA table.
    from dataclasses import asdict
    from app.refdata.service import ReferenceService
    ref_enrich = ReferenceService(session)
    origin_res_for_iata = await ref_enrich.resolve(effective_origin)
    origin_res_for_iata_d = origin_res_for_iata.to_dict()
    origin_iata = (
        origin_res_for_iata_d["airport"]["iata"]
        if origin_res_for_iata_d.get("airport")
        else None
    )

    enriched_results = []
    for idx, it in enumerate(built, start=1):
        it.rank = idx
        d = asdict(it)
        d["origin_iata"] = origin_iata
        # Resolve destination IATA via refdata. We use the country
        # bias we already determined in the build phase (which has
        # been cross-validated against the LocationResolver) so the
        # IATA lookup is consistent with the rest of the response.
        dest_res = await ref_enrich.resolve(
            it.destination,
            country_bias=it.destination_country_code,
        )
        dest_res_d = dest_res.to_dict()
        d["destination_iata"] = (
            dest_res_d["airport"]["iata"] if dest_res_d.get("airport") else None
        )
        # The build phase already set destination_country_code via
        # the LocationResolver cross-check. We override what the
        # refdata re-resolution returns because the refdata may
        # have picked a different (smaller) city with the same
        # name. Trust the consensus pick.
        d["destination_country_alpha2"] = it.destination_country_code
        d["destination_city_id"] = dest_res_d["city"]["id"] if dest_res_d.get("city") else None
        # T8a: per-event window from the build phase (keyed by destination
        # name so the post-sort rank doesn't matter).
        d["event_window"] = event_windows_by_dest.get(it.destination)
        enriched_results.append(d)

    # Audit (no PII, just summary).
    try:
        await AuditService.record(
            session,
            actor_user_id=user.id,
            actor_kind=ActorKind.USER,
            action="itineraries.discover",
            target_kind="user",
            target_id=user.id,
            metadata={
                "interest_count": len(interests),
                "candidate_count": len(candidates),
                "results_returned": len(built),
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "origin": effective_origin,
            },
        )
        await session.commit()
    except Exception:  # noqa: BLE001
        # Don't lose the response on audit failure.
        await session.rollback()

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
        },
        "interests": interests,
        "anchors": {
            "origin": effective_origin,
            "origin_iata": origin_iata,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "destination_override": destination,
        },
        # The active window that the algorithm searched within. Same as
        # ``anchors.date_from/to`` for the default case, but the front-end
        # should display this so the user knows what their "no dates"
        # answer actually meant.
        "active_window": active_window,
        "results": enriched_results,
        "sources_used": sorted(set(sources_used)),
        "flight_status": "kiwi_not_configured",  # honest disclosure
    }


async def _discover_anonymous(
    session: AsyncSession,
    origin: str | None,
    destination: str | None,
    interests_param: str | None,
    date_from: date | None,
    date_to: date | None,
    top_n: int,
) -> dict[str, Any]:
    """Anonymous preview — no stored profile.

    Two supported shapes, used for the "show me what you'd find, then
    ask me to sign up" flow:

    - ``?destination=City[&date_from&date_to]`` — single-destination
      preview. Uses the destination as its own origin (no route to
      compute from an unspecified start city) and the default interest
      set (no personalisation).
    - ``?interest=Name[,Name…][&origin&date_from&date_to]`` —
      interest-driven preview: candidate destinations are seeded from
      REAL events in the window (F1 race cities for motorsport
      interests), and each trip is scored with the passed interests.
      This is what the onboarding "building…" phase runs when the
      visitor skipped the destination step.
    """
    interest_names = [
        i.strip() for i in (interests_param or "").split(",") if i.strip()
    ]
    if not destination and not interest_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="anonymous discover requires ?destination=City or ?interest=Name",
        )
    today = date.today()
    if date_from is None:
        date_from = today
    if date_to is None:
        # Sensible default for anonymous preview: next 6 months
        # (same as the legacy /api/discover fallback).
        date_to = today + timedelta(days=180)
    if date_to < date_from:
        raise HTTPException(400, "date_to must be >= date_from")

    # Origin defaults to the destination itself — no stored origin to pull.
    # In the interest-driven mode there is no destination either, so the
    # app's home city (Maputo) is the honest default, matching the
    # signed-in branch's fallback.
    effective_origin = (origin or destination or "Maputo").strip()
    active_window = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "when": None,
        "when_label": (
            "interest-driven preview (next 6 months)"
            if not destination
            else "next 6 months (preview)"
        ),
    }

    nomi = build_nominatim_client()
    osrm = build_osrm_client()
    jolpica = build_jolpica_client()
    holidays_client = build_holidays_client()
    overpass = build_overpass_client()
    season_races = await _season_races_for_window(jolpica, date_from, date_to)

    if destination:
        candidates: list[tuple[str, str | None]] = [(destination.strip(), None)]
    else:
        # Interest-driven preview: seed candidates from REAL events in
        # the window — F1 race cities first (the season list is the
        # event ledger), so the build phase anchors each trip on the
        # actual race dates like the signed-in flow does.
        candidates = []
        for r in season_races:
            # Strict window: the race itself must fall inside it.
            if date_from <= r.starts_at.date() <= date_to:
                candidates.append((r.city, r.country))
        if not candidates:
            raise HTTPException(
                404,
                "no event-anchored destinations found in this window — "
                "pass ?destination=City or set dates that include an event.",
            )

    # Resolve origin via ReferenceService.
    from app.refdata.service import ReferenceService
    ref = ReferenceService(session)
    origin_res = await ref.resolve(effective_origin)
    origin_res_d = origin_res.to_dict()
    origin_geo_obj = None
    sources_used: list[str] = []
    if origin_res_d["matched"] and origin_res_d["city"]:
        sources_used.append("refdata")
        class _OriginGeo:
            lat = origin_res_d["city"]["latitude"]
            lon = origin_res_d["city"]["longitude"]
            display_name = f"{origin_res_d['city']['name']}, {origin_res_d['country']['name']}"
            country_code = origin_res_d["country"]["alpha2"]
        origin_geo_obj = _OriginGeo()
    else:
        try:
            origin_geo = (await nomi.geocode(effective_origin, limit=1))
        except Exception as e:  # noqa: BLE001
            logger.warning("Origin geocode failed: %s", e)
            origin_geo = []
        origin_geo_obj = origin_geo[0] if origin_geo else None

    built: list[Itinerary] = []
    event_windows_by_dest: dict[str, dict] = {}
    # Anonymous: no STORED interests — but when the caller passed
    # ?interest=, personalise the build with those (the pitch says
    # "matches your interest", which is now true). Without interests we
    # run the default-set intersection exactly as before: all real
    # events, races, holidays, and hotels in the trip window, honestly
    # unpersonalised.
    personalised = bool(interest_names)
    for cand_name, cand_hint in candidates:
        try:
            it, ew = await _build_itinerary_for(
                session,
                candidate_name=cand_name,
                candidate_country_hint=cand_hint,
                origin_geo=origin_geo_obj,
                origin_resolution=None,
                date_from=date_from,
                date_to=date_to,
                interests=interest_names,  # personalise when provided
                season_races=season_races,
                holidays_client=holidays_client,
                osrm=osrm,
                nomi=nomi,
                overpass=overpass,
                sources_used=sources_used,
                is_anonymous=not personalised,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Build itinerary for %s failed: %s", cand_name, e)
            continue
        if it is None:
            continue
        built.append(it)
        if ew is not None:
            event_windows_by_dest[it.destination] = ew

    built.sort(key=lambda i: i.score, reverse=True)
    built = built[:top_n]

    from dataclasses import asdict
    from app.refdata.service import ReferenceService as _RS
    ref_enrich = _RS(session)
    origin_res_for_iata = await ref_enrich.resolve(effective_origin)
    origin_res_for_iata_d = origin_res_for_iata.to_dict()
    origin_iata = (
        origin_res_for_iata_d["airport"]["iata"]
        if origin_res_for_iata_d.get("airport")
        else None
    )

    enriched_results = []
    for idx, it in enumerate(built, start=1):
        it.rank = idx
        d = asdict(it)
        d["origin_iata"] = origin_iata
        # Resolve destination IATA via refdata, biased to the
        # country we picked in the build phase (which has been
        # cross-validated against the LocationResolver). The build
        # phase already set it.destination_country_code so the
        # refdata doesn't re-pick the wrong country.
        dest_res = await ref_enrich.resolve(
            it.destination,
            country_bias=it.destination_country_code,
        )
        dest_res_d = dest_res.to_dict()
        d["destination_iata"] = (
            dest_res_d["airport"]["iata"] if dest_res_d.get("airport") else None
        )
        # Override what the refdata re-resolution returns: the
        # build phase's country pick is the consensus and the
        # refdata IATA-only lookup is allowed to disagree about
        # lat/lon but not about country.
        d["destination_country_alpha2"] = it.destination_country_code
        d["destination_city_id"] = dest_res_d["city"]["id"] if dest_res_d.get("city") else None
        d["event_window"] = event_windows_by_dest.get(it.destination)
        enriched_results.append(d)

    return {
        "user": None,  # explicitly anonymous
        "interests": [],
        "anchors": {
            "origin": effective_origin,
            "origin_iata": origin_iata,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "destination_override": destination,
        },
        "active_window": active_window,
        "results": enriched_results,
        "sources_used": sorted(set(sources_used)),
        "flight_status": "kiwi_not_configured",
        "anonymous": True,  # flag for the frontend
    }


__all__ = ["router"]

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
    else:
        # 2. Fall back to Nominatim
        q = candidate_name
        if candidate_country_hint and "," not in q:
            q = f"{q}, {candidate_country_hint}"
        try:
            results = await nomi.geocode(q, limit=1)
        except Exception as e:  # noqa: BLE001
            logger.warning("Nominatim failed for %s: %s", q, e)
            results = []
        if not results:
            return None, None
        d = results[0]
        if "nominatim" not in sources_used:
            sources_used.append("nominatim")
        d_country = (d.country_code or "").upper() or (candidate_country_hint or "").upper()
        d_lat = d.lat
        d_lon = d.lon
        d_name = d.display_name.split(",")[0].strip()
        d_country_name = d.display_name.split(",")[-1].strip()

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
        anchor = holiday_alerts[0]
        anchor_day = date.fromisoformat(anchor["date"])
        win_from, win_to = compute_event_window(anchor_day)
        event_window_meta = {
            "kind": "public_holiday",
            "anchor_name": anchor["name"],
            "anchor_start": anchor["date"],
            "anchor_end": anchor["date"],
            "window_start": win_from.isoformat(),
            "window_end": win_to.isoformat(),
        }

    # T8c: holidays are filtered to the event window (or the profile
    # window if no anchor event was found). The loop above already
    # filtered to the profile window; re-filter to the event window now
    # that we have it.
    if event_window_meta is not None:
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
    if duration > MAX_ITINERARY_DAYS:
        logger.info(
            "Dropping itinerary for %s: window %s..%s (%d days) exceeds cap",
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

    # F1 keyword match for the "anchor events" label. If the user picked
    # an F1-related interest, an F1 race at this destination is the
    # anchor.
    f1_kw = {"f1", "f1 / motorsport", "motorsport", "formula 1", "racing"}
    interests_norm = {i.strip().lower() for i in interests}
    is_f1_trip = bool(interests_norm & f1_kw)

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
    if non_anchor_interests:
        try:
            per_interest = await asyncio.gather(
                *(free_agg.search(
                    interest_key=k,
                    country_alpha2=d_country,
                    start_date=date_from,
                    end_date=date_to,
                    city=candidate_name,
                    limit=5,
                ) for k in non_anchor_interests),
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
                anchor_events.append({
                    "kind": e.get("kind", "event"),
                    "title": e.get("name", "Event"),
                    "date": e.get("starts_at").isoformat() if e.get("starts_at") else None,
                    "city": e.get("city", ""),
                    "country": e.get("country", ""),
                    "source": e.get("source", "wikipedia"),
                    "source_url": e.get("source_url"),
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
        start_date=it_start.isoformat(),
        end_date=it_end.isoformat(),
        duration_days=duration,
        total_distance_km=(route.distance_m / 1000) if route else 0.0,
        races_in_window=races_at,
        holiday_alerts=holiday_alerts,
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


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@router.get("/discover")
async def discover(
    user: Annotated[User | None, Depends(get_optional_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    origin: str | None = Query(None, description="Override the user's origin"),
    destination: str | None = Query(None, description="Override candidate destinations"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    top_n: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    """Ranked itineraries.

    Works for both authenticated and anonymous users:

    - **Signed in:** uses the user's stored interests, intake window,
      and origins. The original behaviour.
    - **Anonymous:** requires ``?destination=City&date_from=...&date_to=...``
      in the URL — no profile to fall back to. Used for the "preview
      before signup" flow on the itineraries page.

    Both branches return the same shape so the frontend renders results
    identically; only the save buttons differ (auth required for save).
    """
    if user is not None:
        return await _discover_for_user(
            session, user, origin, destination, date_from, date_to, top_n,
        )
    return await _discover_anonymous(
        session, origin, destination, date_from, date_to, top_n,
    )


async def _discover_for_user(
    session: AsyncSession,
    user: User,
    origin: str | None,
    destination: str | None,
    date_from: date | None,
    date_to: date | None,
    top_n: int,
) -> dict[str, Any]:
    """Original authenticated flow — uses the user's stored profile."""
    interests = await _load_user_interests(session, user.id)
    if not interests:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="user has no stored interests; cannot run interest-led discover",
        )

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
        # the season as the candidate pool.)
        jolpica = build_jolpica_client()
        try:
            season = await jolpica.fetch_season(date_from.year)
        except Exception as e:  # noqa: BLE001
            logger.warning("Jolpica failed: %s", e)
            season = []
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
        # Resolve destination IATA via refdata
        dest_res = await ref_enrich.resolve(it.destination)
        dest_res_d = dest_res.to_dict()
        d["destination_iata"] = (
            dest_res_d["airport"]["iata"] if dest_res_d.get("airport") else None
        )
        d["destination_country_alpha2"] = dest_res_d["country"]["alpha2"] if dest_res_d.get("country") else None
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
    date_from: date | None,
    date_to: date | None,
    top_n: int,
) -> dict[str, Any]:
    """Anonymous preview — single-destination, no stored profile.

    Used for the "show me what you'd find, then ask me to sign up" flow.
    Requires ``destination`` in the URL. Uses the destination as its own
    origin (no route to compute from an unspecified start city).
    """
    if not destination:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="anonymous discover requires ?destination=City",
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
    effective_origin = (origin or destination).strip()
    active_window = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "when": None,
        "when_label": "next 6 months (preview)",
    }

    candidates: list[tuple[str, str | None]] = [(destination.strip(), None)]

    nomi = build_nominatim_client()
    osrm = build_osrm_client()
    jolpica = build_jolpica_client()
    holidays_client = build_holidays_client()
    overpass = build_overpass_client()
    try:
        season_races = await jolpica.fetch_season(date_from.year)
    except Exception:
        season_races = []

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
    # Anonymous: no stored interests, so the intersection runs without
    # interest weighting. The user can still see all real events, races,
    # holidays, and hotels in the trip window — they just don't get the
    # personalised "matches your F1 interest" pitch. That's honest: we
    # don't have their interests yet.
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
                interests=[],  # anonymous: no personalisation
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
        dest_res = await ref_enrich.resolve(it.destination)
        dest_res_d = dest_res.to_dict()
        d["destination_iata"] = (
            dest_res_d["airport"]["iata"] if dest_res_d.get("airport") else None
        )
        d["destination_country_alpha2"] = dest_res_d["country"]["alpha2"] if dest_res_d.get("country") else None
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

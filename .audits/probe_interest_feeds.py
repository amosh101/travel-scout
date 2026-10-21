"""Check interest_feeds against REAL live feeds, from the api container.
Passes CATALOG KEYS (the same keys the intake flow sends)."""
import asyncio
from datetime import date
from app.clients.interest_feeds import (
    _parse_event_date, verticals_for_interest, _items_for,
    FEEDS_BY_KEY, search_for_trip, clear_caches, REGISTRY,
)

cases = [
    "Cape Town Jazz Festival runs 25 March 2027 on the Greenmarket Square",
    "Grand Prix weekend: 2026-11-15 in Las Vegas",
    "Nov 12, 2027: one-night-only show",
    "tickets on sale next week",
    "12 November 2027 gala dinner",
]
for c in cases:
    print(_parse_event_date(c), "<-", c[:60])
print("verts f1:", verticals_for_interest("f1"))
print("verts jazz:", verticals_for_interest("jazz"))
print("verts food-wine:", verticals_for_interest("food-wine"))
print("verts casino (expect localsahara only):", verticals_for_interest("casino"))


async def t():
    items = await _items_for(FEEDS_BY_KEY["autosport"])
    print("autosport items:", len(items))
    if items:
        print("  sample:", items[0].title[:70], "|", items[0].published)
    evs, notes = await search_for_trip(
        ["f1"], city="São Paulo", country="Brazil",
        start_date=date(2026, 11, 6), end_date=date(2026, 11, 30))
    print("SAO PAULO F1 events:", len(evs), "notes:", notes)
    for e in evs[:5]:
        print("   -", e["date"], e["title"][:60], "|", e["source"])
    evs2, notes2 = await search_for_trip(
        ["food-wine"], city="Johannesburg", country="South Africa",
        start_date=date(2026, 10, 28), end_date=date(2026, 12, 30))
    print("JHB FOOD events:", len(evs2), "notes:", notes2)
    for e in evs2[:5]:
        print("   -", e["date"], e["title"][:60], "|", e["source"])
    evs3, notes3 = await search_for_trip(
        ["jazz"], city="Maputo", country="Mozambique",
        start_date=date(2026, 10, 21), end_date=date(2027, 4, 19))
    print("MAPUTO JAZZ events:", len(evs3), "notes:", notes3)
    for e in evs3[:5]:
        print("   -", e["date"], e["title"][:60], "|", e["source"])
    # replicability: same call again (cache) -> identical
    evs4, notes4 = await search_for_trip(
        ["f1"], city="São Paulo", country="Brazil",
        start_date=date(2026, 11, 6), end_date=date(2026, 11, 30))
    print("REPLICATE f1 == first run:", [e["title"] for e in evs] == [e["title"] for e in evs4])


asyncio.run(t())
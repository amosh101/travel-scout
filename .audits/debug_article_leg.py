import asyncio
from datetime import date, timedelta
from app.clients.free_events import build_free_event_aggregator

async def main():
    wp = build_free_event_aggregator().wikipedia
    today = date.today()
    horizon = today + timedelta(days=150)
    for key in ("film", "marathon", "nightlife"):
        try:
            recs = await asyncio.wait_for(
                wp.search_city_articles(key, city="Amsterdam",
                                        country_alpha2="NL",
                                        start_date=today, end_date=horizon,
                                        limit=8), timeout=15)
            print(key, "->", len(recs or []),
                  [(r.name or "")[:40] for r in (recs or [])[:2]])
        except Exception as e:
            print(key, "EXC", type(e).__name__, str(e)[:160])

asyncio.run(main())
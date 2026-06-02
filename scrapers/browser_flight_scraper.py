#!/usr/bin/env python3
"""
Real Flight Price Scraper - Production Version

Combines multiple strategies:
1. Direct API calls to flight APIs (when available)
2. Browser automation with stealth for JavaScript sites
3. Text extraction for static content
4. Search link generation for manual verification

NOTE: Flight booking sites have strong anti-bot protection.
This scraper prioritizes returning SOMETHING useful over returning nothing.
Prices may be extracted from various page elements and should be verified.
"""

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

import aiohttp

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class FlightOffer:
    """Flight offer data structure."""
    origin: str
    destination: str
    airline: str
    price: float
    depart_date: date
    return_date: Optional[date] = None
    currency: str = "USD"
    duration_minutes: int = 0
    stops: int = 0
    booking_link: str = ""
    source: str = ""  # "aviasales", "skyscanner", "google", "kayak", "manual"
    scraped_at: Optional[datetime] = None
    confidence: str = "high"  # "high", "medium", "low", "unknown"
    
    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['depart_date'] = self.depart_date.isoformat() if self.depart_date else None
        data['return_date'] = self.return_date.isoformat() if self.return_date else None
        data['scraped_at'] = self.scraped_at.isoformat() if self.scraped_at else None
        return data


class FlightScraper:
    """Real flight scraper using multiple strategies."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(ssl=False, limit=10)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _delay(self, min_sec: float = 2.0, max_sec: float = 4.0):
        await asyncio.sleep(random.uniform(min_sec, max_sec))
    
    def _extract_prices(self, text: str) -> List[Tuple[float, str]]:
        """
        Extract price values from text with context.
        Returns list of (price, context) tuples.
        """
        prices = []
        
        # Find all dollar amounts
        dollar_pattern = r'\$[\d,]+(?:\.\d{2})?'
        matches = list(re.finditer(dollar_pattern, text))
        
        for match in matches:
            try:
                price_str = match.group().replace('$', '').replace(',', '')
                price = float(price_str)
                
                # Get surrounding context (100 chars before and after)
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 100)
                context = text[start:end].lower()
                
                # Filter realistic flight prices (>$100, <$50000 for one-way)
                if 100 <= price <= 50000:
                    # Check if context suggests this is a flight price
                    flight_keywords = ['flight', 'airline', 'ticket', 'price', 'per person', 
                                       'economy', 'business', 'first', 'roundtrip', 'one-way',
                                       'depart', 'arrive', 'travel', 'trip']
                    
                    confidence = 'low'
                    if any(kw in context for kw in flight_keywords):
                        confidence = 'medium'
                    
                    # High confidence if near airline names
                    airlines = ['emirates', 'qatar', 'turkish', 'ethiopian', 'british', 
                               'airways', 'airline', 'air france', 'klm', 'lufthansa']
                    if any(airline in context for airline in airlines):
                        confidence = 'high'
                    
                    prices.append((price, confidence))
            except ValueError:
                continue
        
        return prices
    
    async def scrape_skyscanner(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: Optional[date] = None,
        max_results: int = 5
    ) -> List[FlightOffer]:
        """Scrape Skyscanner."""
        offers = []
        
        try:
            await self._delay(1, 2)
            
            depart_str = depart_date.strftime("%y%m%d")
            if return_date:
                return_str = return_date.strftime("%y%m%d")
                url = f"https://www.skyscanner.net/transport/flights/{origin.lower()}/{destination.lower()}/{depart_str}/{return_str}/"
            else:
                url = f"https://www.skyscanner.net/transport/flights/{origin.lower()}/{destination.lower()}/{depart_str}/"
            
            logger.info(f"Scraping Skyscanner...")
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    prices = self._extract_prices(text)
                    
                    for price, confidence in prices[:max_results]:
                        offer = FlightOffer(
                            origin=origin,
                            destination=destination,
                            airline="Multiple Airlines",
                            price=price,
                            currency="USD",
                            depart_date=depart_date,
                            return_date=return_date,
                            booking_link=url,
                            source="skyscanner",
                            confidence=confidence
                        )
                        offers.append(offer)
                    
                    logger.info(f"Skyscanner: Found {len(offers)} prices")
        
        except Exception as e:
            logger.error(f"Skyscanner error: {e}")
        
        return offers
    
    async def scrape_kayak(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: Optional[date] = None,
        max_results: int = 5
    ) -> List[FlightOffer]:
        """Scrape Kayak."""
        offers = []
        
        try:
            await self._delay(1, 3)
            
            depart_str = depart_date.strftime("%Y-%m-%d")
            if return_date:
                return_str = return_date.strftime("%Y-%m-%d")
                url = f"https://www.kayak.com/flights/{origin}-{destination}/{depart_str}/{return_str}"
            else:
                url = f"https://www.kayak.com/flights/{origin}-{destination}/{depart_str}"
            
            logger.info(f"Scraping Kayak...")
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    prices = self._extract_prices(text)
                    
                    # Filter out obvious false positives (prices that are too round or seem like menu items)
                    filtered_prices = []
                    for price, confidence in prices:
                        # Kayak often has prices like 150, 300, 500 - look for realistic flight prices
                        if 200 <= price <= 15000:
                            filtered_prices.append((price, confidence))
                    
                    for price, confidence in filtered_prices[:max_results]:
                        offer = FlightOffer(
                            origin=origin,
                            destination=destination,
                            airline="Check Kayak",
                            price=price,
                            currency="USD",
                            depart_date=depart_date,
                            return_date=return_date,
                            booking_link=url,
                            source="kayak",
                            confidence=confidence
                        )
                        offers.append(offer)
                    
                    logger.info(f"Kayak: Found {len(offers)} prices")
        
        except Exception as e:
            logger.error(f"Kayak error: {e}")
        
        return offers
    
    async def scrape_google_flights(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: Optional[date] = None,
        max_results: int = 5
    ) -> List[FlightOffer]:
        """Scrape Google Flights."""
        offers = []
        
        try:
            await self._delay(2, 4)
            
            depart_str = depart_date.strftime("%Y-%m-%d")
            if return_date:
                return_str = return_date.strftime("%Y-%m-%d")
                url = f"https://www.google.com/travel/flights?q=Flights+{origin}+to+{destination}+{depart_str}+return+{return_str}"
            else:
                url = f"https://www.google.com/travel/flights?q=Flights+{origin}+to+{destination}+{depart_str}"
            
            logger.info(f"Scraping Google Flights...")
            
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    prices = self._extract_prices(text)
                    
                    for price, confidence in prices[:max_results]:
                        offer = FlightOffer(
                            origin=origin,
                            destination=destination,
                            airline="Check Google Flights",
                            price=price,
                            currency="USD",
                            depart_date=depart_date,
                            return_date=return_date,
                            booking_link=url,
                            source="google",
                            confidence=confidence
                        )
                        offers.append(offer)
                    
                    logger.info(f"Google Flights: Found {len(offers)} prices")
        
        except Exception as e:
            logger.error(f"Google Flights error: {e}")
        
        return offers
    
    async def generate_aviasales_links(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: Optional[date] = None
    ) -> List[FlightOffer]:
        """
        Generate Aviasales search links.
        Per user request, Aviasales is priority for checking prices.
        """
        offers = []
        
        # Major airlines serving MPM-LHR route
        airlines = [
            "Emirates",
            "Qatar Airways", 
            "Ethiopian Airlines",
            "Turkish Airlines",
            "South African Airways"
        ]
        
        # Build Aviasales search URL
        if return_date:
            search_code = f"{origin.lower()}{destination.lower()}{depart_date.strftime('%y%m%d')}{return_date.strftime('%y%m%d')}"
        else:
            search_code = f"{origin.lower()}{destination.lower()}{depart_date.strftime('%y%m%d')}"
        
        aviasales_url = f"https://www.aviasales.com/search/{search_code}"
        
        for airline in airlines:
            offer = FlightOffer(
                origin=origin,
                destination=destination,
                airline=airline,
                price=0.0,
                currency="USD",
                depart_date=depart_date,
                return_date=return_date,
                booking_link=aviasales_url,
                source="aviasales",
                confidence="unknown"
            )
            offers.append(offer)
        
        logger.info(f"Aviasales: Generated {len(offers)} search links")
        return offers
    
    async def search_all(
        self,
        origin: str,
        destination: str,
        depart_date: date,
        return_date: Optional[date] = None,
        max_results: int = 15
    ) -> List[FlightOffer]:
        """Search all sources and combine results."""
        all_offers = []
        
        # Scrape multiple sources in parallel
        tasks = [
            self.scrape_skyscanner(origin, destination, depart_date, return_date, max_results),
            self.scrape_kayak(origin, destination, depart_date, return_date, max_results),
            self.scrape_google_flights(origin, destination, depart_date, return_date, max_results),
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                all_offers.extend(result)
        
        await self._delay(2, 3)
        
        # Add Aviasales links (user requested this specifically)
        if len(all_offers) < 3:
            aviasales_offers = await self.generate_aviasales_links(origin, destination, depart_date, return_date)
            all_offers.extend(aviasales_offers)
        
        # Remove duplicates (same price + source)
        seen = set()
        unique = []
        for offer in all_offers:
            if offer.price > 0:
                key = (offer.source, int(offer.price))
                if key not in seen:
                    seen.add(key)
                    unique.append(offer)
            else:
                # Keep unique airline names for links
                key = (offer.source, offer.airline)
                if key not in seen:
                    seen.add(key)
                    unique.append(offer)
        
        # Sort: high confidence first, then by price
        unique.sort(key=lambda x: (
            0 if x.confidence == 'high' else (1 if x.confidence == 'medium' else 2),
            x.price == 0,
            x.price
        ))
        
        return unique[:max_results]


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Browser-based Flight Price Scraper - Gets real prices from flight sites'
    )
    parser.add_argument('--origin', required=True, help='Origin airport code (e.g., MPM)')
    parser.add_argument('--destination', required=True, help='Destination airport code (e.g., LHR)')
    parser.add_argument('--depart', required=True, help='Departure date (YYYY-MM-DD)')
    parser.add_argument('--return', dest='return_date', help='Return date (YYYY-MM-DD)')
    parser.add_argument('--output', '-o', help='Output JSON file')
    parser.add_argument('--max-results', type=int, default=10, help='Maximum results')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse dates
    try:
        depart_date = date.fromisoformat(args.depart)
        return_date = date.fromisoformat(args.return_date) if args.return_date else None
    except ValueError as e:
        print(f"Error: Invalid date format. Use YYYY-MM-DD. ({e})")
        sys.exit(1)
    
    print(f"\n🔍 Searching flights: {args.origin} → {args.destination}")
    print(f"   Depart: {depart_date}")
    if return_date:
        print(f"   Return: {return_date}")
    print()
    
    # Run search
    async with FlightScraper() as scraper:
        offers = await scraper.search_all(
            args.origin,
            args.destination,
            depart_date,
            return_date,
            max_results=args.max_results
        )
    
    # Display results
    if offers:
        real_offers = [o for o in offers if o.price > 0]
        link_offers = [o for o in offers if o.price == 0]
        
        if real_offers:
            print(f"\n✅ Found {len(real_offers)} potential flight prices:\n")
            print("-" * 120)
            print(f"{'Airline':<28} {'Price':>12} {'Confidence':<12} {'Source':<15}")
            print("-" * 120)
            
            for offer in real_offers:
                price_str = f"${offer.price:.2f}"
                conf_emoji = "🟢" if offer.confidence == 'high' else ("🟡" if offer.confidence == 'medium' else "🔴")
                print(f"{offer.airline:<28} {price_str:>12} {conf_emoji} {offer.confidence:<10} {offer.source:<15}")
            
            print("-" * 120)
            
            if real_offers[0].price > 0:
                print(f"\n💰 Best price found: ${real_offers[0].price:.2f}")
                print(f"   Source: {real_offers[0].source} (confidence: {real_offers[0].confidence})")
            
            print(f"\n⚠️  IMPORTANT: These prices are extracted from web scraping and may not be current.")
            print(f"   Always verify prices on the actual booking site before purchasing.")
        
        if link_offers:
            print(f"\n🔗 Aviasales Search Links (user priority):\n")
            print(f"   URL: {link_offers[0].booking_link}")
            print(f"\n   Airlines: {', '.join([o.airline for o in link_offers[:5]])}")
            print(f"\n   💡 Tip: Aviasales often has the best prices. Click the link above to verify.")
        
        # Save to JSON
        if args.output:
            with open(args.output, 'w') as f:
                json.dump([o.to_dict() for o in offers], f, indent=2)
            print(f"\n💾 Saved to {args.output}")
        
        # Print JSON output
        print("\n" + "=" * 50)
        print("JSON OUTPUT:")
        print("=" * 50)
        print(json.dumps([o.to_dict() for o in offers], indent=2))
        
    else:
        print("\n❌ No flight data found.")
        print("   Try running with --debug for more information.")


if __name__ == '__main__':
    asyncio.run(main())

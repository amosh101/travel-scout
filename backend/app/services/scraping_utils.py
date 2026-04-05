"""
Free Proxy Manager for Travel Scout
Uses free proxy lists with rotation and health checking
Zero-cost for proof-of-concept
"""
import asyncio
import aiohttp
import random
from typing import List, Optional, Dict
from datetime import datetime, timedelta


class FreeProxyManager:
    """
    Manages free proxy rotation for scraping.
    Sources proxies from free public lists.
    Includes health checking and rotation.
    """
    
    FREE_PROXY_SOURCES = [
        # Free proxy APIs (rate limited, but free)
        "https://api.proxyscrape.com/v2/?request=get&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
        "https://www.proxy-list.download/api/v1/get?type=http",
    ]
    
    def __init__(self, check_interval_minutes: int = 30):
        self.proxies: List[Dict] = []
        self.working_proxies: List[str] = []
        self.failed_proxies: set = set()
        self.last_fetch: Optional[datetime] = None
        self.check_interval = timedelta(minutes=check_interval_minutes)
        self.current_index = 0
        
    async def fetch_proxies(self) -> List[str]:
        """Fetch fresh proxies from free sources"""
        proxies = []
        
        async with aiohttp.ClientSession() as session:
            for url in self.FREE_PROXY_SOURCES:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            # Parse proxy list (format: ip:port per line)
                            for line in text.strip().split('\n'):
                                line = line.strip()
                                if ':' in line and not line.startswith('#'):
                                    proxies.append(line)
                except Exception:
                    continue
        
        # Also add some known public proxies (may be slow but work for testing)
        public_proxies = [
            # These are examples - in production would use fetched list
            # Format: "ip:port"
        ]
        proxies.extend(public_proxies)
        
        return list(set(proxies))  # Remove duplicates
    
    async def check_proxy(self, proxy: str) -> bool:
        """Check if a proxy is working"""
        try:
            async with aiohttp.ClientSession() as session:
                proxy_url = f"http://{proxy}"
                async with session.get(
                    "https://httpbin.org/ip",
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=5)
                ):
                    return True
        except Exception:
            return False
    
    async def refresh_proxies(self):
        """Refresh and validate proxy list"""
        # Check if we need to refresh
        if self.last_fetch and datetime.utcnow() - self.last_fetch < self.check_interval:
            return
        
        print("🔄 Refreshing free proxy list...")
        
        # Fetch new proxies
        raw_proxies = await self.fetch_proxies()
        
        # Check which ones work (limit to 20 to avoid long startup)
        check_tasks = [self.check_proxy(p) for p in raw_proxies[:20]]
        results = await asyncio.gather(*check_tasks, return_exceptions=True)
        
        working = [
            proxy for proxy, is_working in zip(raw_proxies[:20], results)
            if is_working is True
        ]
        
        self.working_proxies = working
        self.last_fetch = datetime.utcnow()
        
        print(f"✅ Found {len(working)} working proxies out of {len(raw_proxies)} fetched")
    
    def get_proxy(self) -> Optional[str]:
        """Get next proxy in rotation"""
        if not self.working_proxies:
            return None
        
        proxy = self.working_proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.working_proxies)
        return f"http://{proxy}"
    
    async def get_session_with_proxy(self) -> aiohttp.ClientSession:
        """Get aiohttp session with proxy configured"""
        await self.refresh_proxies()
        
        proxy = self.get_proxy()
        if proxy:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            return aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=15)
            ), proxy
        
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ), None


# Anti-bot evasion helpers
class StealthHeaders:
    """Rotating headers to evade bot detection"""
    
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    ]
    
    ACCEPT_LANGUAGES = [
        "en-US,en;q=0.9",
        "en-GB,en;q=0.8",
        "en-CA,en;q=0.9,fr;q=0.8",
    ]
    
    @classmethod
    def get_headers(cls) -> Dict[str, str]:
        """Get randomized headers"""
        return {
            "User-Agent": random.choice(cls.USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": random.choice(cls.ACCEPT_LANGUAGES),
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Cache-Control": "max-age=0",
        }


class RateLimiter:
    """
    Rate limiting with exponential backoff
    Zero-cost protection against blocking
    """
    
    def __init__(self, requests_per_minute: int = 30):
        self.min_interval = 60.0 / requests_per_minute
        self.last_request: Dict[str, float] = {}
        self.failures: Dict[str, int] = {}
        self.backoff_until: Dict[str, float] = {}
    
    async def wait_if_needed(self, domain: str):
        """Wait if we need to respect rate limits"""
        import time
        
        # Check if we're in backoff
        if domain in self.backoff_until:
            wait_time = self.backoff_until[domain] - time.time()
            if wait_time > 0:
                print(f"⏳ Rate limit backoff for {domain}: {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
            del self.backoff_until[domain]
        
        # Normal rate limiting
        if domain in self.last_request:
            elapsed = time.time() - self.last_request[domain]
            if elapsed < self.min_interval:
                wait = self.min_interval - elapsed
                await asyncio.sleep(wait)
        
        self.last_request[domain] = time.time()
    
    def record_failure(self, domain: str):
        """Record a failure and increase backoff"""
        self.failures[domain] = self.failures.get(domain, 0) + 1
        backoff_seconds = min(2 ** self.failures[domain], 300)  # Max 5 min
        import time
        self.backoff_until[domain] = time.time() + backoff_seconds
    
    def record_success(self, domain: str):
        """Reset failure count on success"""
        self.failures[domain] = 0


# Global instances
proxy_manager = FreeProxyManager()
rate_limiter = RateLimiter(requests_per_minute=20)  # Conservative


async def get_stealth_session() -> tuple[aiohttp.ClientSession, Optional[str]]:
    """
    Get a session with stealth headers and optional proxy
    Returns: (session, proxy_url)
    """
    await proxy_manager.refresh_proxies()
    
    proxy = proxy_manager.get_proxy()
    
    headers = StealthHeaders.get_headers()
    
    session = aiohttp.ClientSession(
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=15)
    )
    
    return session, proxy


if __name__ == "__main__":
    async def test():
        print("Testing proxy and stealth headers...")
        
        # Test stealth session
        session, proxy = await get_stealth_session()
        print(f"Proxy: {proxy}")
        print(f"Headers: {session._default_headers}")
        
        # Test request
        try:
            async with session.get("https://httpbin.org/headers") as resp:
                data = await resp.json()
                print(f"\nServer saw these headers:")
                print(json.dumps(data, indent=2))
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await session.close()
    
    import json
    asyncio.run(test())

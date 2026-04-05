"""
Redis Cache Service for Travel Scout
Zero-cost local Redis via Docker
"""
import json
import pickle
from typing import Optional, Any
from datetime import datetime, timedelta
import os

# Try to use Redis, fallback to in-memory dict if not available
try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class CacheService:
    """
    Multi-layer caching: Redis (if available) → In-memory (fallback)
    Zero-cost for proof-of-concept
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.redis: Optional[Any] = None
        self.memory_cache: dict = {}
        self.memory_expiry: dict = {}
        
        # Try Redis connection
        if REDIS_AVAILABLE and redis_url:
            try:
                self.redis = redis.from_url(redis_url, decode_responses=True)
            except Exception:
                self.redis = None
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        # Try Redis first
        if self.redis:
            try:
                value = await self.redis.get(key)
                if value:
                    return json.loads(value)
            except Exception:
                pass
        
        # Fallback to memory cache
        if key in self.memory_cache:
            expiry = self.memory_expiry.get(key)
            if expiry and expiry > datetime.utcnow():
                return self.memory_cache[key]
            else:
                # Expired, clean up
                self.memory_cache.pop(key, None)
                self.memory_expiry.pop(key, None)
        
        return None
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl_seconds: int = 3600
    ) -> bool:
        """Set value in cache with TTL"""
        serialized = json.dumps(value, default=str)
        
        # Try Redis
        if self.redis:
            try:
                await self.redis.setex(key, ttl_seconds, serialized)
                return True
            except Exception:
                pass
        
        # Fallback to memory
        self.memory_cache[key] = value
        self.memory_expiry[key] = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        
        # Memory cleanup: remove expired entries
        self._cleanup_memory()
        return True
    
    def _cleanup_memory(self):
        """Remove expired entries from memory cache"""
        now = datetime.utcnow()
        expired = [
            key for key, expiry in self.memory_expiry.items() 
            if expiry <= now
        ]
        for key in expired:
            self.memory_cache.pop(key, None)
            self.memory_expiry.pop(key, None)
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache"""
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass
        
        self.memory_cache.pop(key, None)
        self.memory_expiry.pop(key, None)
        return True
    
    def generate_flight_cache_key(
        self,
        origin: str,
        destination: str,
        date_from: str,
        date_to: Optional[str] = None,
        max_price: Optional[float] = None
    ) -> str:
        """Generate consistent cache key for flight searches"""
        key_parts = ["flight", origin, destination, date_from]
        if date_to:
            key_parts.append(date_to)
        if max_price:
            key_parts.append(f"max{max_price}")
        return ":".join(key_parts)


# Global cache instance
cache_service = CacheService(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

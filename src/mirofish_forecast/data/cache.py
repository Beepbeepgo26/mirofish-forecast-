import json
import logging

from upstash_redis import Redis

from mirofish_forecast.config.constants import CACHE_PREFIX
from mirofish_forecast.config.settings import Settings

logger = logging.getLogger(__name__)


class CacheClient:
    """Redis cache wrapper using Upstash HTTP-based Redis."""

    def __init__(self, settings: Settings) -> None:
        self._redis = Redis(url=settings.redis_url, token=settings.redis_token)

    def get(self, key: str) -> str | None:
        """Get a cached value. Returns None on miss or error."""
        full_key = f"{CACHE_PREFIX}:{key}"
        try:
            value = self._redis.get(full_key)
            if value is not None:
                logger.debug(f"Cache HIT: {full_key}")
                return value if isinstance(value, str) else json.dumps(value)
            logger.debug(f"Cache MISS: {full_key}")
            return None
        except Exception:
            logger.warning(f"Cache GET error for {full_key}", exc_info=True)
            return None

    def zrevrange(self, key: str, start: int, stop: int) -> list[str]:
        """Get members from sorted set in reverse score order."""
        full_key = f"{CACHE_PREFIX}:{key}"
        try:
            results = self._redis.zrevrange(full_key, start, stop)
            return [r for r in results] if results else []
        except Exception:
            logger.warning(f"Redis zrevrange failed for key={full_key}", exc_info=True)
            return []

    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        """Remove members from sorted set within score range."""
        full_key = f"{CACHE_PREFIX}:{key}"
        try:
            self._redis.zremrangebyscore(full_key, min_score, max_score)
        except Exception:
            logger.warning(f"Redis zremrangebyscore failed for key={full_key}", exc_info=True)
            return None

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Set a cached value with TTL. Silently fails on error."""
        full_key = f"{CACHE_PREFIX}:{key}"
        try:
            self._redis.set(full_key, value, ex=ttl_seconds)
            logger.debug(f"Cache SET: {full_key} (TTL={ttl_seconds}s)")
        except Exception:
            logger.warning(f"Cache SET error for {full_key}", exc_info=True)

    def delete(self, key: str) -> None:
        """Delete a cached key. Silently fails on error."""
        full_key = f"{CACHE_PREFIX}:{key}"
        try:
            self._redis.delete(full_key)
            logger.debug(f"Cache DEL: {full_key}")
        except Exception:
            logger.warning(f"Cache DEL error for {full_key}", exc_info=True)

    def health_check(self) -> bool:
        """Returns True if Redis is reachable."""
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

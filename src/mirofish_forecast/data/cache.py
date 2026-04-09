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

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """Set a cached value with TTL. Silently fails on error."""
        full_key = f"{CACHE_PREFIX}:{key}"
        try:
            self._redis.set(full_key, value, ex=ttl_seconds)
            logger.debug(f"Cache SET: {full_key} (TTL={ttl_seconds}s)")
        except Exception:
            logger.warning(f"Cache SET error for {full_key}", exc_info=True)

    def health_check(self) -> bool:
        """Returns True if Redis is reachable."""
        try:
            self._redis.ping()
            return True
        except Exception:
            return False

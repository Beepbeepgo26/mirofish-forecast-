import logging
from datetime import datetime

import fear_and_greed

from mirofish_forecast.config import constants
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import FearGreedData

logger = logging.getLogger(__name__)


class FearGreedClient:
    """Fetches the CNN Fear & Greed Index."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    def get_fear_greed(self) -> FearGreedData:
        """Fetch current Fear & Greed. Returns empty on error — never crashes."""
        cache_key = "fg:current"
        cached = self._cache.get(cache_key)
        if cached:
            return FearGreedData.model_validate_json(cached)

        try:
            data = fear_and_greed.get()
            result = FearGreedData(
                value=float(data.value),
                description=data.description,
                last_updated=datetime.utcnow(),
            )
            self._cache.set(cache_key, result.model_dump_json(), constants.CACHE_TTL_FEAR_GREED)
            return result

        except Exception:
            logger.warning("Fear & Greed fetch failed", exc_info=True)
            return FearGreedData()

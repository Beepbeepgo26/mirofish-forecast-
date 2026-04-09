import logging
from datetime import datetime

import requests

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import MarketInternals

logger = logging.getLogger(__name__)


class IBClient:
    """Fetches NYSE market internals (TICK, ADD, VOLD) from the IB relay."""

    def __init__(self, settings: Settings, cache: CacheClient) -> None:
        self._base_url = settings.ib_relay_url.rstrip("/")
        self._cache = cache

    def _fetch_value(self, endpoint: str) -> float | None:
        """Fetch a single value from the IB relay. Returns None on error."""
        try:
            resp = requests.get(
                f"{self._base_url}{endpoint}",
                timeout=constants.DATA_FETCH_TIMEOUT,
            )
            resp.raise_for_status()
            return float(resp.json().get("value", 0))
        except Exception:
            logger.warning(f"IB relay fetch failed: {endpoint}", exc_info=True)
            return None

    def get_market_internals(self) -> MarketInternals:
        """Fetch TICK, ADD, VOLD. Returns partial data on errors — never crashes."""
        cache_key = "ib:internals"
        cached = self._cache.get(cache_key)
        if cached:
            return MarketInternals.model_validate_json(cached)

        result = MarketInternals(
            nyse_tick=self._fetch_value(constants.IB_ENDPOINT_TICK),
            nyse_add=self._fetch_value(constants.IB_ENDPOINT_ADD),
            nyse_vold=self._fetch_value(constants.IB_ENDPOINT_VOLD),
            as_of=datetime.utcnow(),
        )

        self._cache.set(cache_key, result.model_dump_json(), constants.CACHE_TTL_MARKET_INTERNALS)
        return result

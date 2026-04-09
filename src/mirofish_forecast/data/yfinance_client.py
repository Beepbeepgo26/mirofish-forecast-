import logging
from datetime import datetime

import yfinance as yf

from mirofish_forecast.config import constants
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import CrossAssetSnapshot

logger = logging.getLogger(__name__)


class YFinanceClient:
    """Fetches cross-asset prices from yfinance."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    def get_cross_asset_snapshot(self) -> CrossAssetSnapshot:
        """Fetch latest prices for cross-asset context. Returns partial on error."""
        cache_key = "cross_asset:snapshot"
        cached = self._cache.get(cache_key)
        if cached:
            return CrossAssetSnapshot.model_validate_json(cached)

        prices: dict[str, float | None] = {}
        try:
            tickers_str = " ".join(constants.YFINANCE_TICKERS.values())
            data = yf.download(
                tickers_str, period="1d", interval="1m", progress=False, threads=True
            )

            for name, ticker in constants.YFINANCE_TICKERS.items():
                try:
                    if ("Close", ticker) in data.columns:
                        latest = data[("Close", ticker)].dropna().iloc[-1]
                        prices[f"{name}_price"] = round(float(latest), 2)
                    else:
                        prices[f"{name}_price"] = None
                except (KeyError, IndexError):
                    prices[f"{name}_price"] = None

        except Exception:
            logger.warning("yfinance download failed", exc_info=True)

        result = CrossAssetSnapshot(**prices, as_of=datetime.utcnow())
        self._cache.set(cache_key, result.model_dump_json(), constants.CACHE_TTL_CROSS_ASSET)
        return result

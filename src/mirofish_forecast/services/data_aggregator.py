import logging
from datetime import datetime

from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.data.fear_greed_client import FearGreedClient
from mirofish_forecast.data.fred_client import FredClient
from mirofish_forecast.data.ib_client import IBClient
from mirofish_forecast.data.vix_client import VixClient
from mirofish_forecast.data.yfinance_client import YFinanceClient
from mirofish_forecast.models.market import MarketContext

logger = logging.getLogger(__name__)


class DataAggregator:
    """Orchestrates all data source clients into a unified MarketContext."""

    def __init__(self, settings: Settings) -> None:
        self._cache = CacheClient(settings)
        self._fred = FredClient(settings, self._cache)
        self._vix = VixClient(self._cache)
        self._fear_greed = FearGreedClient(self._cache)
        self._yfinance = YFinanceClient(self._cache)
        self._ib = IBClient(settings, self._cache)

    def get_market_context(self) -> MarketContext:
        """Pull from all sources and assemble MarketContext.

        Each client handles its own errors — partial data is acceptable.
        """
        logger.info("Assembling market context from all data sources")

        macro = self._fred.get_macro_indicators()
        vix = self._vix.get_vix_data()
        cross_asset = self._yfinance.get_cross_asset_snapshot()
        fear_greed = self._fear_greed.get_fear_greed()
        internals = self._ib.get_market_internals()

        context = MarketContext(
            macro=macro,
            vix=vix,
            cross_asset=cross_asset,
            fear_greed=fear_greed,
            internals=internals,
            assembled_at=datetime.utcnow(),
        )

        logger.info("Market context assembled successfully")
        return context

    def health_check(self) -> dict[str, bool]:
        """Check connectivity of cache and data sources."""
        return {
            "redis": self._cache.health_check(),
        }

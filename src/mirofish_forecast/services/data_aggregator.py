import logging
from datetime import datetime

from mirofish_forecast.config import constants
from mirofish_forecast.config.constants import get_instrument_config
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.data.databento_client import DatabentoClient
from mirofish_forecast.data.economic_calendar import EconomicCalendarClient
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
        self._calendar = EconomicCalendarClient(settings, self._cache)
        self._databento = DatabentoClient(settings, self._cache)

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

        # Override CME prices with Databento (much fresher than yfinance)
        if self._databento.is_enabled and self._databento.is_live_writer_healthy():
            overrides = {}
            for instrument, field in [
                ("ES", "es_price"),
                ("NQ", "nq_price"),
                ("CL", "crude_price"),
                ("GC", "gc_price"),
            ]:
                db_price = self._databento.get_latest_price(instrument)
                if db_price is not None:
                    overrides[field] = db_price
            if overrides:
                cross_asset = cross_asset.model_copy(update=overrides)

        # Pull economic calendar events
        try:
            events_today = self._calendar.get_events_today()
            events_week = self._calendar.get_events_this_week()
        except Exception:
            logger.warning("Calendar fetch failed", exc_info=True)
            events_today = []
            events_week = []

        context = MarketContext(
            macro=macro,
            vix=vix,
            cross_asset=cross_asset,
            fear_greed=fear_greed,
            internals=internals,
            events_today=events_today,
            events_this_week=events_week,
            assembled_at=datetime.utcnow(),
        )

        logger.info("Market context assembled successfully")
        return context

    def get_instrument_price(self, instrument: str) -> float | None:
        """Get current price — Databento first, yfinance fallback."""
        if self._databento.is_enabled and instrument.upper() in constants.DATABENTO_SYMBOL_MAP:
            price = self._databento.get_latest_price(instrument)
            if price is not None:
                return price

        config = get_instrument_config(instrument)
        ticker = config["yfinance_ticker"]

        cache_key = f"price:{instrument.lower()}"
        cached = self._cache.get(cache_key)
        if cached:
            try:
                return float(cached)
            except (TypeError, ValueError):
                pass

        try:
            import yfinance as yf

            data = yf.Ticker(ticker)
            price = data.fast_info.last_price
            if price:
                price = round(float(price), config["price_decimals"])
                self._cache.set(cache_key, str(price), constants.CACHE_TTL_OHLCV)
                return price
        except Exception:
            logger.warning(
                f"Failed to fetch price for {instrument} ({ticker})",
                exc_info=True,
            )

        return None

    def health_check(self) -> dict[str, bool]:
        """Check connectivity of cache and data sources."""
        return {
            "redis": self._cache.health_check(),
        }

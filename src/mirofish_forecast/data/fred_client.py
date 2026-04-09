import logging
from datetime import datetime

from fredapi import Fred

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import MacroIndicators

logger = logging.getLogger(__name__)

# Map of our field names to FRED series IDs
_SERIES_MAP = {
    "fed_funds_rate": constants.FRED_SERIES_FED_FUNDS,
    "ten_year_yield": constants.FRED_SERIES_10Y_YIELD,
    "two_year_yield": constants.FRED_SERIES_2Y_YIELD,
    "ten_year_2_year_spread": constants.FRED_SERIES_10Y_2Y_SPREAD,
    "vix_close": constants.FRED_SERIES_VIX_CLOSE,
    "cpi_yoy": constants.FRED_SERIES_CPI,
    "unemployment_rate": constants.FRED_SERIES_UNEMPLOYMENT,
    "gdp_growth": constants.FRED_SERIES_GDP,
}


class FredClient:
    """Fetches macro indicators from the FRED API."""

    def __init__(self, settings: Settings, cache: CacheClient) -> None:
        self._fred = Fred(api_key=settings.fred_api_key)
        self._cache = cache

    def get_macro_indicators(self) -> MacroIndicators:
        """Fetch all macro indicators. Returns partial data on errors — never crashes."""
        cache_key = "fred:macro"
        cached = self._cache.get(cache_key)
        if cached:
            return MacroIndicators.model_validate_json(cached)

        values: dict[str, float | None] = {}
        for field_name, series_id in _SERIES_MAP.items():
            try:
                series = self._fred.get_series(series_id, observation_start="2024-01-01")
                latest = series.dropna().iloc[-1] if not series.dropna().empty else None
                values[field_name] = float(latest) if latest is not None else None
            except Exception:
                logger.warning(f"FRED fetch failed for {series_id}", exc_info=True)
                values[field_name] = None

        result = MacroIndicators(**values, as_of=datetime.utcnow())
        self._cache.set(cache_key, result.model_dump_json(), constants.CACHE_TTL_FRED)
        return result

"""Fetches macro indicators from the FRED API."""

import logging
from datetime import datetime

from fredapi import Fred

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import MacroIndicators

logger = logging.getLogger(__name__)

# Simple series: latest value is directly usable as-is
_SIMPLE_SERIES_MAP = {
    "fed_funds_rate": constants.FRED_SERIES_FED_FUNDS,
    "ten_year_yield": constants.FRED_SERIES_10Y_YIELD,
    "two_year_yield": constants.FRED_SERIES_2Y_YIELD,
    "ten_year_2_year_spread": constants.FRED_SERIES_10Y_2Y_SPREAD,
    "vix_close": constants.FRED_SERIES_VIX_CLOSE,
    "unemployment_rate": constants.FRED_SERIES_UNEMPLOYMENT,
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

        # Fetch simple series (latest value is directly usable)
        for field_name, series_id in _SIMPLE_SERIES_MAP.items():
            try:
                series = self._fred.get_series(series_id, observation_start="2024-01-01")
                latest = series.dropna().iloc[-1] if not series.dropna().empty else None
                values[field_name] = round(float(latest), 2) if latest is not None else None
            except Exception:
                logger.warning(f"FRED fetch failed for {series_id}", exc_info=True)
                values[field_name] = None

        # Fetch CPI YoY % — try the direct OECD series first, fall back to manual calc
        values["cpi_yoy"] = self._fetch_cpi_yoy()

        # Fetch GDP growth % — already annualized quarterly rate
        values["gdp_growth"] = self._fetch_latest_value(constants.FRED_SERIES_GDP_GROWTH)

        result = MacroIndicators(**values, as_of=datetime.utcnow())
        self._cache.set(cache_key, result.model_dump_json(), constants.CACHE_TTL_FRED)
        return result

    def _fetch_latest_value(self, series_id: str) -> float | None:
        """Fetch the latest non-null value from a FRED series."""
        try:
            series = self._fred.get_series(series_id, observation_start="2024-01-01")
            if series.dropna().empty:
                return None
            return round(float(series.dropna().iloc[-1]), 2)
        except Exception:
            logger.warning(f"FRED fetch failed for {series_id}", exc_info=True)
            return None

    def _fetch_cpi_yoy(self) -> float | None:
        """Fetch CPI YoY percentage change.

        Primary: CPALTT01USM657N (OECD CPI YoY % directly)
        Fallback: Manual calculation from CPIAUCSL raw index
        """
        # Try the direct YoY series first
        direct = self._fetch_latest_value(constants.FRED_SERIES_CPI_YOY)
        if direct is not None:
            return direct

        # Fallback: compute YoY from raw CPI index
        try:
            series = self._fred.get_series(
                constants.FRED_SERIES_CPI, observation_start="2023-01-01"
            )
            clean = series.dropna()
            if len(clean) < 13:
                return None
            current = float(clean.iloc[-1])
            year_ago = float(clean.iloc[-13])  # 12 months back
            yoy = round(((current - year_ago) / year_ago) * 100, 2)
            return yoy
        except Exception:
            logger.warning("CPI YoY fallback calculation failed", exc_info=True)
            return None

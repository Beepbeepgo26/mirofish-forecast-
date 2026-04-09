import logging

import vix_utils

from mirofish_forecast.config import constants
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.market import VIXData, VIXRegime, VIXTermStructure

logger = logging.getLogger(__name__)


def _classify_vix_regime(vix: float) -> VIXRegime:
    if vix < constants.VIX_REGIME_COMPLACENT:
        return VIXRegime.COMPLACENT
    elif vix < constants.VIX_REGIME_NORMAL:
        return VIXRegime.NORMAL
    elif vix < constants.VIX_REGIME_ELEVATED:
        return VIXRegime.ELEVATED
    return VIXRegime.FEAR


def _classify_term_structure(front: float, second: float) -> VIXTermStructure:
    spread = second - front
    if spread > 0.5:
        return VIXTermStructure.CONTANGO
    elif spread < -0.5:
        return VIXTermStructure.BACKWARDATION
    return VIXTermStructure.FLAT


class VixClient:
    """Fetches VIX spot and term structure via vix_utils."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    def get_vix_data(self) -> VIXData:
        """Fetch VIX data. Returns partial data on errors — never crashes."""
        cache_key = "vix:term_structure"
        cached = self._cache.get(cache_key)
        if cached:
            return VIXData.model_validate_json(cached)

        try:
            futures = vix_utils.download_vix_futures()
            if futures.empty:
                logger.warning("vix_utils returned empty futures data")
                return VIXData()

            # Get the two nearest expiry months
            # vix_utils returns a DataFrame with columns per expiry
            cols = sorted(futures.columns)
            latest_row = futures.iloc[-1]

            front_val = float(latest_row[cols[0]]) if len(cols) > 0 else None
            second_val = float(latest_row[cols[1]]) if len(cols) > 1 else None

            # VIX spot from the Fear & Greed / yfinance — use front month as proxy here
            spot = front_val

            regime = _classify_vix_regime(spot) if spot else None
            structure = (
                _classify_term_structure(front_val, second_val)
                if front_val and second_val
                else None
            )
            spread = round(second_val - front_val, 2) if front_val and second_val else None

            result = VIXData(
                spot=spot,
                regime=regime,
                front_month=front_val,
                second_month=second_val,
                term_structure=structure,
                contango_spread=spread,
            )
            self._cache.set(cache_key, result.model_dump_json(), constants.CACHE_TTL_VIX_TERM)
            return result

        except Exception:
            logger.warning("VIX data fetch failed", exc_info=True)
            return VIXData()

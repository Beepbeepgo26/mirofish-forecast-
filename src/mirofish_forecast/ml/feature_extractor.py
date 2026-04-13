"""FeatureExtractor — computes ML features from MarketContext + OHLCV bars.

Produces a flat numpy array of ~25 features that LightGBM can consume.
All features are designed to be:
1. Available in real-time (no lookahead)
2. Stationary or slowly varying (no raw prices as features)
3. Meaningful for ES futures price direction
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from mirofish_forecast.config import constants
from mirofish_forecast.models.market import MarketContext

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Canonical feature order — models are trained on this exact ordering
FEATURE_NAMES = [
    # Price momentum (4)
    "return_1bar",
    "return_3bar",
    "return_6bar",
    "return_12bar",
    # Volatility (4)
    "realized_vol_20",
    "vol_percentile_rank",
    "vix_spot",
    "vix_regime_encoded",
    # Trend (4)
    "consecutive_up_bars",
    "consecutive_down_bars",
    "body_pct_mean_5",
    "bar_range_mean_5",
    # Volume (2)
    "volume_zscore",
    "volume_ratio_5_20",
    # Macro (4)
    "yield_spread_2s10s",
    "fear_greed",
    "cpi_yoy",
    "fed_funds_rate",
    # Session (3)
    "minutes_since_rth_open",
    "session_type_encoded",
    "day_of_week_encoded",
    # Cross-asset (3)
    "dxy_return_1d",
    "tlt_return_1d",
    "crude_return_1d",
    # Horizon (1)
    "horizon_minutes",
]


class FeatureExtractor:
    """Computes ML feature vector from market data."""

    def __init__(self) -> None:
        self._feature_names = FEATURE_NAMES

    @property
    def feature_names(self) -> list[str]:
        """Canonical feature name ordering."""
        return self._feature_names

    @property
    def feature_count(self) -> int:
        """Number of features in the vector."""
        return len(self._feature_names)

    def extract(
        self,
        context: MarketContext,
        ohlcv_bars: list[dict],
        horizon_minutes: int,
    ) -> np.ndarray:
        """Extract features from current market state.

        Args:
            context: Full MarketContext from DataAggregator
            ohlcv_bars: Recent OHLCV bar dicts with keys:
                        time, open, high, low, close, volume
            horizon_minutes: Forecast horizon in minutes

        Returns:
            numpy array of shape (n_features,)
        """
        features: dict[str, float] = {}
        closes = np.array([b["close"] for b in ohlcv_bars]) if ohlcv_bars else np.array([])

        # --- Price momentum ---
        for window in constants.FEATURE_MOMENTUM_WINDOWS:
            key = f"return_{window}bar"
            if len(closes) > window:
                ret = (closes[-1] - closes[-(window + 1)]) / closes[-(window + 1)]
                features[key] = float(ret)
            else:
                features[key] = 0.0

        # --- Volatility ---
        vol_win = constants.FEATURE_VOL_WINDOW
        if len(closes) >= vol_win:
            log_rets = np.diff(np.log(np.maximum(closes[-vol_win - 1 :], 1e-9)))
            features["realized_vol_20"] = float(np.std(log_rets))
            features["vol_percentile_rank"] = 0.5
        else:
            features["realized_vol_20"] = 0.0
            features["vol_percentile_rank"] = 0.5

        features["vix_spot"] = context.vix.spot or 20.0
        vix_map = {
            "complacent": 0,
            "normal": 1,
            "elevated": 2,
            "fear": 3,
        }
        features["vix_regime_encoded"] = float(
            vix_map.get(
                context.vix.regime.value if context.vix.regime else "normal",
                1,
            )
        )

        # --- Trend ---
        if len(closes) >= 2:
            up_count, down_count = 0, 0
            for i in range(len(closes) - 1, 0, -1):
                if closes[i] > closes[i - 1]:
                    if down_count == 0:
                        up_count += 1
                    else:
                        break
                elif closes[i] < closes[i - 1]:
                    if up_count == 0:
                        down_count += 1
                    else:
                        break
                else:
                    break
            features["consecutive_up_bars"] = float(up_count)
            features["consecutive_down_bars"] = float(down_count)
        else:
            features["consecutive_up_bars"] = 0.0
            features["consecutive_down_bars"] = 0.0

        if len(ohlcv_bars) >= 5:
            recent = ohlcv_bars[-5:]
            body_pcts = [
                abs(b["close"] - b["open"]) / max(b["high"] - b["low"], 0.01) for b in recent
            ]
            bar_ranges = [b["high"] - b["low"] for b in recent]
            features["body_pct_mean_5"] = float(np.mean(body_pcts))
            features["bar_range_mean_5"] = float(np.mean(bar_ranges))
        else:
            features["body_pct_mean_5"] = 0.5
            features["bar_range_mean_5"] = 0.0

        # --- Volume ---
        volumes = np.array([b.get("volume", 0) for b in ohlcv_bars]) if ohlcv_bars else np.array([])
        if len(volumes) >= 20:
            vol_mean = float(np.mean(volumes[-20:]))
            vol_std = float(np.std(volumes[-20:]))
            features["volume_zscore"] = float((volumes[-1] - vol_mean) / max(vol_std, 1))
            vol_5 = float(np.mean(volumes[-5:]))
            features["volume_ratio_5_20"] = vol_5 / max(vol_mean, 1)
        else:
            features["volume_zscore"] = 0.0
            features["volume_ratio_5_20"] = 1.0

        # --- Macro ---
        features["yield_spread_2s10s"] = context.macro.ten_year_2_year_spread or 0.0
        features["fear_greed"] = (context.fear_greed.value or 50.0) / 100.0
        features["cpi_yoy"] = context.macro.cpi_yoy or 0.0
        features["fed_funds_rate"] = context.macro.fed_funds_rate or 0.0

        # --- Session ---
        now_et = datetime.now(ET)
        if now_et.weekday() < 5:
            rth_open = now_et.replace(
                hour=constants.RTH_OPEN_HOUR,
                minute=constants.RTH_OPEN_MINUTE,
                second=0,
            )
            if now_et >= rth_open:
                features["minutes_since_rth_open"] = (now_et - rth_open).total_seconds() / 60
            else:
                features["minutes_since_rth_open"] = -1.0
        else:
            features["minutes_since_rth_open"] = -1.0

        if now_et.weekday() >= 5:
            features["session_type_encoded"] = 4.0
        elif 9 * 60 + 30 <= now_et.hour * 60 + now_et.minute < 16 * 60:
            features["session_type_encoded"] = 0.0
        elif now_et.hour >= 8:
            features["session_type_encoded"] = 1.0
        else:
            features["session_type_encoded"] = 3.0

        features["day_of_week_encoded"] = float(now_et.weekday())

        # --- Cross-asset (placeholders for inference) ---
        features["dxy_return_1d"] = 0.0
        features["tlt_return_1d"] = 0.0
        features["crude_return_1d"] = 0.0

        # --- Horizon ---
        features["horizon_minutes"] = float(horizon_minutes)

        return np.array(
            [features.get(name, 0.0) for name in self._feature_names],
            dtype=np.float32,
        )

    def extract_from_historical(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        opens: np.ndarray,
        volumes: np.ndarray,
        idx: int,
        horizon_minutes: int,
        vix: float = 20.0,
        fear_greed: float = 50.0,
        yield_spread: float = 0.0,
        cpi_yoy: float = 3.0,
        fed_funds: float = 5.0,
    ) -> np.ndarray:
        """Extract features from historical arrays at a specific index.

        Used for batch training data generation. No MarketContext needed.

        Args:
            closes/highs/lows/opens/volumes: Full historical arrays
            idx: Current bar index (features look backward from here)
            horizon_minutes: Target horizon for the forecast
            vix/fear_greed/etc: Macro values (approximated)

        Returns:
            numpy array of shape (n_features,)
        """
        f = np.zeros(len(self._feature_names), dtype=np.float32)

        # Price momentum (indices 0-3)
        for i, window in enumerate(constants.FEATURE_MOMENTUM_WINDOWS):
            if idx >= window:
                f[i] = (closes[idx] - closes[idx - window]) / max(closes[idx - window], 1e-9)

        # Realized vol (index 4)
        vol_win = constants.FEATURE_VOL_WINDOW
        if idx >= vol_win:
            log_r = np.diff(np.log(np.maximum(closes[idx - vol_win : idx + 1], 1e-9)))
            f[4] = float(np.std(log_r))
        f[5] = 0.5  # vol_percentile_rank
        f[6] = vix  # vix_spot
        vix_enc = 0 if vix < 15 else 1 if vix < 20 else 2 if vix < 30 else 3
        f[7] = float(vix_enc)

        # Trend (indices 8-11)
        if idx >= 1:
            up, down = 0, 0
            for j in range(idx, max(idx - 20, 0), -1):
                if closes[j] > closes[j - 1]:
                    if down == 0:
                        up += 1
                    else:
                        break
                elif closes[j] < closes[j - 1]:
                    if up == 0:
                        down += 1
                    else:
                        break
                else:
                    break
            f[8] = float(up)
            f[9] = float(down)

        if idx >= 5:
            bp, br = [], []
            for j in range(idx - 4, idx + 1):
                rng = max(highs[j] - lows[j], 0.01)
                bp.append(abs(closes[j] - opens[j]) / rng)
                br.append(highs[j] - lows[j])
            f[10] = float(np.mean(bp))
            f[11] = float(np.mean(br))

        # Volume (indices 12-13)
        if idx >= 20:
            v20 = np.mean(volumes[idx - 19 : idx + 1])
            vs = np.std(volumes[idx - 19 : idx + 1])
            f[12] = float((volumes[idx] - v20) / max(vs, 1))
            v5 = np.mean(volumes[idx - 4 : idx + 1])
            f[13] = float(v5 / max(v20, 1))

        # Macro (indices 14-17)
        f[14] = yield_spread
        f[15] = fear_greed / 100.0
        f[16] = cpi_yoy
        f[17] = fed_funds

        # Session (indices 18-20, approximated)
        f[18] = float((idx % 78) * 5)  # minutes_since_rth_open
        f[19] = 0.0  # session_type_encoded (RTH)
        f[20] = float(idx % 5)  # day_of_week_encoded

        # Cross-asset (indices 21-23, not available)
        f[21] = 0.0
        f[22] = 0.0
        f[23] = 0.0

        # Horizon (index 24)
        f[24] = float(horizon_minutes)

        return f

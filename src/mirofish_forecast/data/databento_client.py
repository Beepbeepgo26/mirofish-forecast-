"""Databento client — reads real-time bars from Redis (written by Live Writer)
and calls Historical API for anything older than 24 hours.

Covers: ES, NQ, CL, GC via GLBX.MDP3 (CME Globex).
Does NOT cover: DXY, TLT, VIX, SPY, QQQ (use yfinance for these).
"""

import json
import logging
from datetime import datetime, timedelta, timezone

import numpy as np

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient

logger = logging.getLogger(__name__)


class DatabentoClient:
    """Reads CME futures data from Redis (live) and Databento Historical API."""

    def __init__(self, settings: Settings, cache: CacheClient) -> None:
        self._api_key = settings.databento_api_key
        self._cache = cache
        self._enabled = bool(self._api_key)

        if not self._enabled:
            logger.warning(
                "Databento API key not configured — falling back to yfinance"
            )

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def is_live_writer_healthy(self) -> bool:
        """Check if the Live Writer sidecar is running."""
        heartbeat = self._cache.get(constants.DATABENTO_WRITER_HEARTBEAT)
        return heartbeat is not None

    # -------------------------------------------------------------------
    # Real-time data (from Redis, written by Live Writer)
    # -------------------------------------------------------------------

    def get_latest_price(self, instrument: str = "ES") -> float | None:
        """Get the most recent price from Redis.

        The Live Writer updates this every minute when a new bar closes.
        Returns None if Live Writer isn't running or instrument not found.
        """
        key = f"{constants.DATABENTO_PRICE_KEY_PREFIX}:{instrument.upper()}"
        raw = self._cache.get(key)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
        return None

    def get_recent_bars(
        self,
        instrument: str = "ES",
        count: int = 78,
    ) -> list[dict]:
        """Get recent 1-minute bars from Redis.

        The Live Writer stores bars in a sorted set keyed by timestamp.
        We read the most recent N bars.

        Args:
            instrument: "ES", "NQ", "CL", "GC"
            count: Number of bars to retrieve

        Returns:
            List of bar dicts sorted oldest → newest
        """
        list_key = f"{constants.DATABENTO_BARLIST_PREFIX}:{instrument.upper()}"

        try:
            # Get the most recent N bar keys from the sorted set
            bar_keys = self._cache.zrevrange(list_key, 0, count - 1)
            if not bar_keys:
                return []

            # Read each bar
            bars: list[dict] = []
            for bar_key in reversed(bar_keys):  # Reverse to get oldest-first
                raw = self._cache.get(bar_key)
                if raw:
                    try:
                        bars.append(json.loads(raw))
                    except Exception:
                        pass

            return bars

        except Exception:
            logger.warning(
                f"Failed to read bars from Redis for {instrument}",
                exc_info=True,
            )
            return []

    def get_5min_bars(
        self,
        instrument: str = "ES",
        count: int = 78,
    ) -> list[dict]:
        """Get 5-minute bars by resampling 1-minute bars from Redis.

        Args:
            instrument: "ES", "NQ", "CL", "GC"
            count: Number of 5-min bars to return

        Returns:
            List of resampled 5-min bar dicts
        """
        # Need 5x the 1-min bars
        raw_bars = self.get_recent_bars(instrument, count=count * 5 + 5)
        if not raw_bars:
            return []

        return self._resample_to_5min(raw_bars)[-count:]

    # -------------------------------------------------------------------
    # Historical data (from Databento Historical API, >24h old)
    # -------------------------------------------------------------------

    def get_training_data(
        self,
        instrument: str = "ES",
        lookback_days: int = 365,
        schema: str = "ohlcv-1h",
    ) -> tuple[np.ndarray, ...] | None:
        """Get bulk historical data for model training.

        Uses Databento Historical API — only works for data >24h old.

        Args:
            instrument: "ES"
            lookback_days: Days of history (up to ~2500 for 7 years)
            schema: "ohlcv-1m", "ohlcv-1h", "ohlcv-1d"

        Returns:
            Tuple of (closes, highs, lows, opens, volumes) or None
        """
        if not self._enabled:
            return None

        symbol = constants.DATABENTO_SYMBOL_MAP.get(instrument.upper())
        if not symbol:
            return None

        try:
            import databento as db

            client = db.Historical(self._api_key)
            now = datetime.now(timezone.utc)
            # Start from lookback_days ago, end at 25 hours ago (24h embargo + buffer)
            start = now - timedelta(days=lookback_days)
            end = now - timedelta(hours=25)

            logger.info(
                f"Databento Historical: fetching {schema} for {symbol} "
                f"from {start.date()} to {end.date()}"
            )

            data = client.timeseries.get_range(
                dataset=constants.DATABENTO_DATASET,
                symbols=symbol,
                stype_in="continuous",
                schema=schema,
                start=start.isoformat(),
                end=end.isoformat(),
            )

            df = data.to_df()

            if df.empty or len(df) < 200:
                logger.warning(f"Databento: insufficient data ({len(df)} bars)")
                return None

            closes = df["close"].values.flatten().astype(np.float64)
            highs = df["high"].values.flatten().astype(np.float64)
            lows = df["low"].values.flatten().astype(np.float64)
            opens = df["open"].values.flatten().astype(np.float64)
            volumes = df["volume"].values.flatten().astype(np.float64)

            logger.info(f"Databento: fetched {len(closes)} {schema} bars")
            return closes, highs, lows, opens, volumes

        except Exception:
            logger.error("Databento training data fetch failed", exc_info=True)
            return None

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _resample_to_5min(self, bars_1m: list[dict]) -> list[dict]:
        """Resample 1-minute bars to 5-minute bars."""
        if not bars_1m:
            return []

        result: list[dict] = []
        bucket: list[dict] = []

        for bar in bars_1m:
            bucket.append(bar)
            if len(bucket) == 5:
                result.append({
                    "time": bucket[0]["time"],
                    "open": bucket[0]["open"],
                    "high": max(b["high"] for b in bucket),
                    "low": min(b["low"] for b in bucket),
                    "close": bucket[-1]["close"],
                    "volume": sum(b.get("volume", 0) for b in bucket),
                })
                bucket = []

        # Don't discard the remainder — it's the current incomplete bar
        if bucket:
            result.append({
                "time": bucket[0]["time"],
                "open": bucket[0]["open"],
                "high": max(b["high"] for b in bucket),
                "low": min(b["low"] for b in bucket),
                "close": bucket[-1]["close"],
                "volume": sum(b.get("volume", 0) for b in bucket),
            })

        return result

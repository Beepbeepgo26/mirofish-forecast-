"""Databento client — reads real-time bars from Redis (written by Live Writer)
and calls Historical API for anything older than 24 hours.

Covers: ES, NQ, CL, GC via GLBX.MDP3 (CME Globex).
Does NOT cover: DXY, TLT, VIX, SPY, QQQ (use yfinance for these).
"""

import json
import logging
import time
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
        """Check whether the live 1m bar feed is current.

        Healthy iff the newest ES 1m bar in Redis is at most
        DATABENTO_MAX_BAR_AGE_SECONDS old. The writer heartbeat key is deliberately
        not consulted: a running writer that stores no bars is not healthy, and a
        lapsed heartbeat while bars keep landing is not unhealthy. Reads unhealthy
        during the CME maintenance halt and on weekends, which is the honest answer.
        """
        bars = self.get_recent_bars("ES", count=1)
        if not bars:
            logger.debug("Live writer unhealthy: no ES 1m bars in Redis")
            return False
        # A bar without a time is treated as infinitely old.
        age = time.time() - float(bars[-1].get("time", 0))
        healthy = age <= constants.DATABENTO_MAX_BAR_AGE_SECONDS
        logger.debug(
            f"Live writer {'healthy' if healthy else 'unhealthy'}: newest ES 1m bar is "
            f"{age:.0f}s old (max {constants.DATABENTO_MAX_BAR_AGE_SECONDS}s)"
        )
        return healthy

    # -------------------------------------------------------------------
    # Real-time data (from Redis, written by Live Writer)
    # -------------------------------------------------------------------

    def get_latest_price(self, instrument: str = "ES") -> float | None:
        """Get the most recent price: the close of the newest 1m bar in Redis.

        Read from the bar list, never from the 10-second-TTL price key, so the value
        is available for as long as bars are. Returns None if the instrument has no
        bars.
        """
        bars = self.get_recent_bars(instrument, count=1)
        if not bars:
            return None
        try:
            return float(bars[-1]["close"])
        except (KeyError, TypeError, ValueError):
            logger.warning(
                f"Newest {instrument.upper()} 1m bar has no usable close: {bars[-1]}"
            )
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
        include_incomplete: bool = False,
    ) -> list[dict]:
        """Get wall-clock-aligned 5-minute bars by resampling 1-minute bars from Redis.

        Args:
            instrument: "ES", "NQ", "CL", "GC"
            count: Number of 5-min bars to return
            include_incomplete: Also return partial buckets, flagged ``complete=False``.
                By default only complete buckets are returned, so the result can be
                shorter than ``count`` and never includes the currently forming bar.

        Returns:
            List of resampled 5-min bar dicts, oldest first, every ``time`` on a
            5-minute boundary
        """
        # Fetch margin: the oldest bucket in a zrevrange window is usually cut by
        # the window edge, so over-fetch two buckets' worth of 1-min bars.
        raw_bars = self.get_recent_bars(
            instrument, count=count * constants.DATABENTO_BARS_PER_BUCKET + 10
        )
        if not raw_bars:
            return []

        bars_5m = self._resample_to_5min(raw_bars)
        if include_incomplete:
            return bars_5m[-count:]

        newest = len(bars_5m) - 1
        complete_bars: list[dict] = []
        for index, bar in enumerate(bars_5m):
            if bar["complete"]:
                complete_bars.append(bar)
            elif index in (0, newest):
                # Window-edge artefact: the oldest bucket was cut by the fetch window,
                # the newest is the currently forming bar. Expected, not a data problem.
                logger.debug(
                    f"Dropping incomplete 5m bar {bar['time']} for {instrument} "
                    f"({bar['bar_count']}/{constants.DATABENTO_BARS_PER_BUCKET} 1m bars, "
                    "window edge)"
                )
            else:
                # Interior gap: 1m bars missing mid-history. A writer fault, or a
                # no-trade minute (Databento prints no record for those).
                logger.warning(
                    f"Dropping incomplete 5m bar {bar['time']} for {instrument}: "
                    f"{bar['bar_count']}/{constants.DATABENTO_BARS_PER_BUCKET} 1m bars "
                    "(interior gap)"
                )
        return complete_bars[-count:]

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
        """Resample 1-minute bars into wall-clock-aligned 5-minute bars.

        Bars are bucketed by ``time // DATABENTO_BAR_BUCKET_SECONDS`` rather than by
        arrival order, so every output ``time`` is a 5-minute boundary no matter where
        the fetch window happened to start. Each output bar also carries ``complete``
        (exactly DATABENTO_BARS_PER_BUCKET bars at offsets 0, 60, ..., 240 from the
        bucket start) and ``bar_count``.
        """
        if not bars_1m:
            return []

        bucket_seconds = constants.DATABENTO_BAR_BUCKET_SECONDS
        bars_per_bucket = constants.DATABENTO_BARS_PER_BUCKET
        expected_offsets = set(range(0, bucket_seconds, bucket_seconds // bars_per_bucket))

        # bucket_start -> {bar time -> bar}; a duplicated time keeps the last one seen.
        buckets: dict[int, dict[int, dict]] = {}
        for bar in bars_1m:
            bar_time = int(bar["time"])
            bucket_start = (bar_time // bucket_seconds) * bucket_seconds
            buckets.setdefault(bucket_start, {})[bar_time] = bar

        result: list[dict] = []
        for bucket_start in sorted(buckets):
            by_time = buckets[bucket_start]
            ordered = [by_time[bar_time] for bar_time in sorted(by_time)]
            # Times are unique within a bucket, so matching the offset set also
            # pins the count to exactly bars_per_bucket.
            offsets = {bar_time - bucket_start for bar_time in by_time}
            result.append({
                "time": bucket_start,
                "open": ordered[0]["open"],
                "high": max(b["high"] for b in ordered),
                "low": min(b["low"] for b in ordered),
                "close": ordered[-1]["close"],
                "volume": sum(b.get("volume", 0) for b in ordered),
                "complete": offsets == expected_offsets,
                "bar_count": len(ordered),
            })

        return result

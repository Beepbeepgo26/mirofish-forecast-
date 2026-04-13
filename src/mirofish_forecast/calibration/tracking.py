"""Forecast tracking — stores predictions and checks actuals.

Uses Upstash Redis for storage (simple key-value, no GCS dependency for Phase 5).
Each forecast is stored as a JSON blob keyed by forecast_id.
A list key tracks all forecast IDs for iteration.
"""

import json
import logging
from datetime import datetime, timedelta

import yfinance as yf

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.forecast import (
    ForecastResult,
    ForecastTracking,
)

logger = logging.getLogger(__name__)


class ForecastTracker:
    """Stores forecast predictions and checks them against actuals."""

    def __init__(self, settings: Settings) -> None:
        self._cache = CacheClient(settings)

    def store_forecast(
        self,
        forecast: ForecastResult,
        vix_at_forecast: float | None = None,
        fear_greed_at_forecast: float | None = None,
        agent_disagreement: float = 0.0,
        market_regime: str | None = None,
    ) -> ForecastTracking:
        """Store a forecast for future outcome checking."""
        tracking = ForecastTracking(
            forecast_id=forecast.forecast_id,
            instrument=forecast.instrument,
            forecast_horizon_minutes=forecast.forecast_horizon_minutes,
            created_at=datetime.utcnow(),
            current_price=forecast.current_price,
            predicted_median=forecast.distribution.median,
            predicted_p5=forecast.distribution.percentile_5,
            predicted_p25=forecast.distribution.percentile_25,
            predicted_p75=forecast.distribution.percentile_75,
            predicted_p95=forecast.distribution.percentile_95,
            predicted_prob_up=forecast.distribution.prob_up,
            predicted_prob_down=forecast.distribution.prob_down,
            predicted_prob_flat=forecast.distribution.prob_flat,
            vix_at_forecast=vix_at_forecast,
            fear_greed_at_forecast=fear_greed_at_forecast,
            agent_disagreement=agent_disagreement,
            sim_success_rate=(forecast.successful_simulations / max(forecast.total_simulations, 1)),
            sim_preset=forecast.sim_preset,
            market_regime=market_regime,
        )

        # Store in Redis with long TTL
        key = f"{constants.TRACKING_STORAGE_PREFIX}:{forecast.forecast_id}"
        ttl = constants.TRACKING_MAX_AGE_DAYS * 86400
        self._cache.set(key, tracking.model_dump_json(), ttl)

        # Add to index list
        self._add_to_index(forecast.forecast_id)

        logger.info(f"Stored forecast tracking: {forecast.forecast_id}")
        return tracking

    def check_outcome(self, forecast_id: str) -> ForecastTracking | None:
        """Check the actual price and score the forecast.

        Returns updated tracking record, or None if forecast not found.
        """
        key = f"{constants.TRACKING_STORAGE_PREFIX}:{forecast_id}"
        raw = self._cache.get(key)
        if not raw:
            logger.warning(f"Tracking record not found: {forecast_id}")
            return None

        tracking = ForecastTracking.model_validate_json(raw)

        if tracking.outcome_checked:
            return tracking

        # Check if enough time has passed
        horizon_end = tracking.created_at + timedelta(
            minutes=tracking.forecast_horizon_minutes + constants.TRACKING_CHECK_DELAY_MINUTES
        )
        if datetime.utcnow() < horizon_end:
            logger.debug(f"Too early to check {forecast_id}, horizon not elapsed")
            return tracking

        # Compute when the forecast horizon expired
        target_time = tracking.created_at + timedelta(minutes=tracking.forecast_horizon_minutes)
        actual_price = self._fetch_actual_price(tracking.instrument, target_time)
        if actual_price is None:
            logger.warning(f"Could not fetch actual price for {forecast_id}")
            return tracking

        # Score the forecast
        flat_threshold = tracking.current_price * 0.001
        actual_return = (actual_price - tracking.current_price) / tracking.current_price * 100

        if actual_price > tracking.current_price + flat_threshold:
            actual_direction = "up"
        elif actual_price < tracking.current_price - flat_threshold:
            actual_direction = "down"
        else:
            actual_direction = "flat"

        # Determine predicted direction (majority probability)
        if tracking.predicted_prob_up > max(
            tracking.predicted_prob_down, tracking.predicted_prob_flat
        ):
            predicted_direction = "up"
        elif tracking.predicted_prob_down > max(
            tracking.predicted_prob_up, tracking.predicted_prob_flat
        ):
            predicted_direction = "down"
        else:
            predicted_direction = "flat"

        updated = tracking.model_copy(
            update={
                "actual_price": actual_price,
                "actual_direction": actual_direction,
                "actual_return_pct": round(actual_return, 4),
                "outcome_checked": True,
                "outcome_checked_at": datetime.utcnow(),
                "p50_hit": tracking.predicted_p25 <= actual_price <= tracking.predicted_p75,
                "p90_hit": tracking.predicted_p5 <= actual_price <= tracking.predicted_p95,
                "direction_correct": predicted_direction == actual_direction,
                "absolute_error": round(abs(tracking.predicted_median - actual_price), 2),
            }
        )

        # Update stored record
        ttl = constants.TRACKING_MAX_AGE_DAYS * 86400
        self._cache.set(key, updated.model_dump_json(), ttl)

        logger.info(
            f"Checked forecast {forecast_id}: "
            f"predicted={tracking.predicted_median:.2f}, "
            f"actual={actual_price:.2f}, "
            f"error={updated.absolute_error:.2f}, "
            f"direction_correct={updated.direction_correct}"
        )
        return updated

    def check_all_pending(self) -> list[ForecastTracking]:
        """Check all forecasts that haven't been scored yet."""
        ids = self._get_index()
        checked: list[ForecastTracking] = []
        for fid in ids:
            result = self.check_outcome(fid)
            if result and result.outcome_checked:
                checked.append(result)
        return checked

    def get_all_tracked(self) -> list[ForecastTracking]:
        """Retrieve all tracking records."""
        ids = self._get_index()
        records: list[ForecastTracking] = []
        for fid in ids:
            key = f"{constants.TRACKING_STORAGE_PREFIX}:{fid}"
            raw = self._cache.get(key)
            if raw:
                try:
                    records.append(ForecastTracking.model_validate_json(raw))
                except Exception:
                    logger.warning(f"Failed to parse tracking record: {fid}")
        return records

    def get_scored_forecasts(self) -> list[ForecastTracking]:
        """Get only forecasts with known outcomes."""
        return [r for r in self.get_all_tracked() if r.outcome_checked]

    def get_calibration_features(self) -> list[dict]:
        """Extract feature vectors for CQR training from scored forecasts."""
        scored = self.get_scored_forecasts()
        features: list[dict] = []
        for r in scored:
            features.append(
                {
                    "forecast_id": r.forecast_id,
                    # Features
                    "vix": r.vix_at_forecast,
                    "fear_greed": r.fear_greed_at_forecast,
                    "agent_disagreement": r.agent_disagreement,
                    "sim_success_rate": r.sim_success_rate,
                    "predicted_std": r.predicted_p95 - r.predicted_p5,
                    "horizon_minutes": r.forecast_horizon_minutes,
                    "predicted_prob_up": r.predicted_prob_up,
                    "predicted_prob_down": r.predicted_prob_down,
                    # Targets (residuals)
                    "residual": (r.actual_price or 0) - r.predicted_median,
                    "abs_residual": r.absolute_error or 0,
                    "actual_price": r.actual_price,
                    "predicted_median": r.predicted_median,
                }
            )
        return features

    def _fetch_actual_price(self, instrument: str, target_time: datetime) -> float | None:
        """Fetch the price at target_time using yfinance historical bars.

        Pulls a window of 1-minute bars around target_time and picks the
        close of the bar nearest to that time. Falls back to 5-minute bars
        over a wider window if 1-minute data is unavailable.

        Args:
            instrument: Instrument code (ES, NQ, CL, GC)
            target_time: The UTC datetime when the forecast horizon expired

        Returns:
            The close price nearest to target_time, or None if unavailable
        """
        ticker_map = {
            "ES": "ES=F",
            "NQ": "NQ=F",
            "CL": "CL=F",
            "GC": "GC=F",
        }
        ticker = ticker_map.get(instrument, "ES=F")

        try:
            # Try 1-minute bars in a 30-minute window around target
            start = target_time - timedelta(minutes=15)
            end = target_time + timedelta(minutes=15)

            data = yf.download(
                ticker,
                start=start.strftime("%Y-%m-%d %H:%M:%S"),
                end=end.strftime("%Y-%m-%d %H:%M:%S"),
                interval="1m",
                progress=False,
            )

            if data.empty:
                # Fallback: 5-minute bars over a wider window
                start_wide = target_time - timedelta(hours=1)
                end_wide = target_time + timedelta(hours=1)
                data = yf.download(
                    ticker,
                    start=start_wide.strftime("%Y-%m-%d %H:%M:%S"),
                    end=end_wide.strftime("%Y-%m-%d %H:%M:%S"),
                    interval="5m",
                    progress=False,
                )

            if data.empty:
                # Final fallback: current price (better than nothing)
                logger.warning(
                    f"No historical bars for {ticker} near {target_time}, "
                    "falling back to current price"
                )
                tick = yf.Ticker(ticker)
                price = tick.fast_info.last_price
                return round(float(price), 2) if price else None

            # Remove timezone info for comparison
            data.index = data.index.tz_localize(None)
            diffs = abs(data.index - target_time)
            closest_idx = diffs.argmin()
            return round(float(data.iloc[closest_idx]["Close"]), 2)

        except Exception:
            logger.warning(
                f"Failed to fetch actual price for {ticker} at {target_time}",
                exc_info=True,
            )
            return None

    def _add_to_index(self, forecast_id: str) -> None:
        """Add forecast_id to the tracking index list."""
        index_key = f"{constants.TRACKING_STORAGE_PREFIX}:index"
        existing = self._cache.get(index_key)
        if existing:
            try:
                ids = json.loads(existing)
            except Exception:
                ids = []
        else:
            ids = []

        if forecast_id not in ids:
            ids.append(forecast_id)
            # Keep only the last 1000 entries
            if len(ids) > 1000:
                ids = ids[-1000:]
            ttl = constants.TRACKING_MAX_AGE_DAYS * 86400
            self._cache.set(index_key, json.dumps(ids), ttl)

    def _get_index(self) -> list[str]:
        """Get the list of tracked forecast IDs."""
        index_key = f"{constants.TRACKING_STORAGE_PREFIX}:index"
        raw = self._cache.get(index_key)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except Exception:
            return []

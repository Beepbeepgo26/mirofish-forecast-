"""SyntheticBootstrapper — generates fake forecast/outcome pairs from
historical OHLCV to cold-start CQR calibration.

Pulls 1 year of hourly ES bars from yfinance. For each sample, creates a
ForecastTracking record as if we had made a forecast at that time and then
checked the outcome. This gives CQR real price dynamics to learn from
without waiting months for organic data.

Uses the existing ForecastTracking model — no new models needed.
"""

import json
import logging
import random
from datetime import datetime, timedelta

import numpy as np
import yfinance as yf

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.forecast import ForecastTracking

logger = logging.getLogger(__name__)

BOOTSTRAP_COUNT = 500
BOOTSTRAP_HORIZONS = [30, 60, 120, 240]  # Minutes
BOOTSTRAP_LOOKBACK_DAYS = 365
BOOTSTRAP_STATUS_KEY = "calibration:bootstrap_status"


class SyntheticBootstrapper:
    """Generates synthetic ForecastTracking records from historical data."""

    def __init__(self, settings: Settings) -> None:
        self._cache = CacheClient(settings)
        self._settings = settings

    def run(self) -> dict:
        """Generate synthetic forecast/outcome pairs and store them.

        Idempotent — skips if bootstrap already ran.

        Returns:
            Dict with generation results
        """
        # Check if bootstrap already ran
        status = self._cache.get(BOOTSTRAP_STATUS_KEY)
        if status == "complete":
            logger.info("Bootstrap already complete, skipping")
            return {
                "generated": 0,
                "message": "Bootstrap already complete",
            }

        logger.info(f"Starting synthetic bootstrap: {BOOTSTRAP_COUNT} samples")

        # Pull historical hourly data
        closes = self._fetch_historical()
        if closes is None or len(closes) < 200:
            logger.error("Insufficient historical data for bootstrap")
            return {
                "generated": 0,
                "error": "Insufficient historical data",
            }

        generated = 0
        samples_per_horizon = BOOTSTRAP_COUNT // len(BOOTSTRAP_HORIZONS)

        for horizon in BOOTSTRAP_HORIZONS:
            # Convert horizon (minutes) to hourly bar offset
            hourly_ahead = max(1, horizon // 60)

            if hourly_ahead >= len(closes):
                logger.warning(f"Horizon {horizon}min too long for data, skipping")
                continue

            count = self._generate_for_horizon(closes, horizon, hourly_ahead, samples_per_horizon)
            generated += count
            logger.info(f"Generated {count} synthetic samples for {horizon}min horizon")

        # Mark complete
        self._cache.set(BOOTSTRAP_STATUS_KEY, "complete", 86400 * 365)

        logger.info(f"Bootstrap complete: {generated} total synthetic samples")
        return {"generated": generated}

    def reset(self) -> None:
        """Clear bootstrap status so it can run again.

        Does NOT delete synthetic records — they'll age out via TTL.
        """
        self._cache.delete(BOOTSTRAP_STATUS_KEY)
        logger.info("Bootstrap status reset")

    def get_status(self) -> str:
        """Get current bootstrap status."""
        return self._cache.get(BOOTSTRAP_STATUS_KEY) or "not_run"

    def _fetch_historical(self) -> np.ndarray | None:
        """Fetch 1 year of hourly ES bars."""
        try:
            end = datetime.utcnow()
            start = end - timedelta(days=BOOTSTRAP_LOOKBACK_DAYS)

            data = yf.download(
                "ES=F",
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1h",
                progress=False,
            )

            if data.empty:
                return None

            # Handle MultiIndex columns (yfinance v0.2.31+)
            if hasattr(data.columns, "levels"):
                data.columns = data.columns.get_level_values(0)

            closes = data["Close"].dropna().values.flatten()
            logger.info(f"Fetched {len(closes)} hourly bars for bootstrap")
            return closes

        except Exception:
            logger.error("Failed to fetch historical data", exc_info=True)
            return None

    def _generate_for_horizon(
        self,
        closes: np.ndarray,
        horizon_minutes: int,
        hourly_ahead: int,
        sample_count: int,
    ) -> int:
        """Generate synthetic ForecastTracking records for one horizon.

        For each sample:
        1. Pick a random historical bar as the "forecast time"
        2. current_price = close at that bar
        3. actual_price = close at bar + hourly_ahead
        4. Simulate what our Monte Carlo would have predicted
        5. Score the forecast and store as ForecastTracking
        """
        max_idx = len(closes) - hourly_ahead - 1
        if max_idx < 10:
            return 0

        rng = random.Random(42 + horizon_minutes)
        indices = [rng.randint(0, max_idx) for _ in range(sample_count)]
        count = 0

        for idx in indices:
            current_price = float(closes[idx])
            actual_price = float(closes[idx + hourly_ahead])

            if current_price <= 0:
                continue

            tracking = self._build_synthetic_record(
                rng,
                idx,
                horizon_minutes,
                current_price,
                actual_price,
            )

            # Store in Redis using the same key pattern as ForecastTracker
            key = f"{constants.TRACKING_STORAGE_PREFIX}:{tracking.forecast_id}"
            ttl = constants.TRACKING_MAX_AGE_DAYS * 86400
            self._cache.set(key, tracking.model_dump_json(), ttl)

            # Add to the tracking index
            self._add_to_index(tracking.forecast_id)
            count += 1

        return count

    def _build_synthetic_record(
        self,
        rng: random.Random,
        idx: int,
        horizon_minutes: int,
        current_price: float,
        actual_price: float,
    ) -> ForecastTracking:
        """Build a single synthetic ForecastTracking record."""
        actual_return = (actual_price - current_price) / current_price
        forecast_noise = rng.gauss(0, 0.003)
        simulated_return = actual_return * 0.6 + forecast_noise

        predicted_median = round(current_price * (1 + simulated_return), 2)

        # Simulate uncertainty (wider for longer horizons)
        horizon_scale = (horizon_minutes / 60) ** 0.5
        sim_std = current_price * 0.003 * horizon_scale
        predicted_p5 = round(predicted_median - 1.645 * sim_std, 2)
        predicted_p95 = round(predicted_median + 1.645 * sim_std, 2)
        predicted_p25 = round(predicted_median - 0.675 * sim_std, 2)
        predicted_p75 = round(predicted_median + 0.675 * sim_std, 2)

        # Simulate direction probabilities
        prob_up, prob_down, prob_flat = self._simulate_probs(rng, simulated_return)

        # Determine actual direction
        flat_thr = current_price * 0.001
        if actual_price > current_price + flat_thr:
            actual_direction = "up"
        elif actual_price < current_price - flat_thr:
            actual_direction = "down"
        else:
            actual_direction = "flat"

        # Determine predicted direction (binary + confidence gate)
        max_prob = max(prob_up, prob_down)
        if max_prob < constants.ML_DIRECTION_CONFIDENCE_THRESHOLD:
            predicted_direction = "flat"  # Abstention
        elif prob_up >= prob_down:
            predicted_direction = "up"
        else:
            predicted_direction = "down"

        created_at = datetime.utcnow() - timedelta(hours=rng.randint(1, 720))
        forecast_id = f"synth_{horizon_minutes}m_{idx}"

        return ForecastTracking(
            forecast_id=forecast_id,
            instrument="ES",
            forecast_horizon_minutes=horizon_minutes,
            created_at=created_at,
            current_price=current_price,
            predicted_median=predicted_median,
            predicted_p5=predicted_p5,
            predicted_p25=predicted_p25,
            predicted_p75=predicted_p75,
            predicted_p95=predicted_p95,
            predicted_prob_up=round(prob_up, 3),
            predicted_prob_down=round(prob_down, 3),
            predicted_prob_flat=round(prob_flat, 3),
            vix_at_forecast=round(rng.uniform(14, 32), 1),
            fear_greed_at_forecast=round(rng.uniform(15, 80), 1),
            agent_disagreement=round(sim_std, 2),
            sim_success_rate=round(rng.uniform(0.85, 1.0), 2),
            sim_preset="synthetic",
            market_regime=rng.choice(
                [
                    "tight_range",
                    "trending_up",
                    "trending_down",
                    "volatile_chop",
                ]
            ),
            actual_price=actual_price,
            actual_direction=actual_direction,
            actual_return_pct=round(actual_return * 100, 4),
            outcome_checked=True,
            outcome_checked_at=created_at + timedelta(minutes=horizon_minutes + 5),
            p50_hit=predicted_p25 <= actual_price <= predicted_p75,
            p90_hit=predicted_p5 <= actual_price <= predicted_p95,
            direction_correct=(predicted_direction == actual_direction),
            absolute_error=round(abs(predicted_median - actual_price), 2),
        )

    @staticmethod
    def _simulate_probs(rng: random.Random, simulated_return: float) -> tuple[float, float, float]:
        """Simulate direction probabilities from a return.

        Binary model: prob_down + prob_up ≈ 1.0, prob_flat = 0.0.
        Low-confidence predictions set prob_flat > 0 as abstention indicator.
        """
        if abs(simulated_return) > 0.001:
            # Confident directional prediction
            if simulated_return > 0:
                prob_up = 0.55 + min(abs(simulated_return) * 40, 0.35)
                prob_down = 1.0 - prob_up
            else:
                prob_down = 0.55 + min(abs(simulated_return) * 40, 0.35)
                prob_up = 1.0 - prob_down
            prob_flat = 0.0
        else:
            # Near threshold — model would abstain
            prob_up = 0.48 + rng.uniform(-0.05, 0.05)
            prob_down = 1.0 - prob_up
            prob_flat = 0.0

        return round(prob_up, 3), round(prob_down, 3), round(prob_flat, 3)

    def _add_to_index(self, forecast_id: str) -> None:
        """Add to the same index that ForecastTracker uses."""
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
            if len(ids) > 1000:
                ids = ids[-1000:]
            ttl = constants.TRACKING_MAX_AGE_DAYS * 86400
            self._cache.set(index_key, json.dumps(ids), ttl)

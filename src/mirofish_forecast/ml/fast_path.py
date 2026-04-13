"""FastPathRunner — sub-5s forecast using LightGBM models.

Skips Monte Carlo entirely. Uses:
1. FeatureExtractor on current MarketContext + OHLCV
2. LightGBM direction classifier → P(up/down/flat)
3. LightGBM quantile regressors → P5, P95 price interval
4. GPT-4o synthesis → natural language paragraph
"""

import logging
import time
from datetime import datetime

import numpy as np

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.llm.client import LLMClient
from mirofish_forecast.ml.feature_extractor import FeatureExtractor
from mirofish_forecast.ml.model_store import ModelStore
from mirofish_forecast.models.forecast import FastPathResult
from mirofish_forecast.models.market import MarketContext

logger = logging.getLogger(__name__)

# Cross-asset feature indices excluded from direction model
_CROSS_ASSET_INDICES = [21, 22, 23]

FAST_SYNTHESIS_PROMPT = (
    "You are a futures market analyst. "
    "Generate a brief, confident forecast paragraph.\n\n"
    "Instrument: {instrument}\n"
    "Horizon: {horizon_minutes} minutes\n"
    "Current price: {current_price}\n\n"
    "Model prediction:\n"
    "- Direction: {direction} ({confidence:.0%} confidence)\n"
    "- P(up): {prob_up:.1%}, P(down): {prob_down:.1%}, "
    "P(flat): {prob_flat:.1%}\n"
    "- 90% price interval: {p5:.2f} – {p95:.2f}\n"
    "- Median estimate: {median:.2f}\n\n"
    "Market context:\n"
    "- VIX: {vix} ({vix_regime})\n"
    "- Fear & Greed: {fear_greed}\n\n"
    "Write 2-3 sentences. Lead with the directional call "
    "and confidence. Mention the price range. Be concise "
    "and decisive — this is a fast forecast, not a "
    "detailed analysis."
)


class FastPathRunner:
    """Runs LightGBM inference for sub-5s forecasts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cache = CacheClient(settings)
        self._store = ModelStore(self._cache)
        self._extractor = FeatureExtractor()
        self._llm = LLMClient(settings)
        self._models_loaded = False
        self._dir_model: object | None = None
        self._q_low_model: object | None = None
        self._q_high_model: object | None = None

    def is_available(self) -> bool:
        """Check if fast path models are loaded and ready."""
        if not self._models_loaded:
            self._load_models()
        return self._models_loaded

    def run(
        self,
        context: MarketContext,
        ohlcv_bars: list[dict],
        instrument: str,
        horizon_minutes: int,
        forecast_id: str,
        pipeline_start_time: float,
        cross_asset_returns: dict[str, float] | None = None,
    ) -> FastPathResult:
        """Run the fast path inference.

        Args:
            context: MarketContext from DataAggregator
            ohlcv_bars: Recent OHLCV bars for feature extraction
            instrument: "ES", "NQ", etc.
            horizon_minutes: Forecast horizon
            forecast_id: Unique ID
            pipeline_start_time: time.time() when pipeline started

        Returns:
            FastPathResult with direction probabilities and price interval
        """
        if not self._models_loaded:
            self._load_models()

        if not self._models_loaded:
            raise RuntimeError("Fast path models not available")

        # Step 1: Extract features
        features = self._extractor.extract(
            context,
            ohlcv_bars,
            horizon_minutes,
            cross_asset_returns=cross_asset_returns,
        )

        # Step 2: LightGBM inference
        t0 = time.time()
        x_input = features.reshape(1, -1)

        # Direction probabilities (classes: 0=down, 1=flat, 2=up)
        # Direction model was trained on 22 features (no cross-asset)
        keep_mask = np.ones(x_input.shape[1], dtype=bool)
        keep_mask[_CROSS_ASSET_INDICES] = False
        x_dir = x_input[:, keep_mask]
        dir_probs = self._dir_model.predict_proba(x_dir)[0]  # type: ignore[union-attr]
        prob_down = float(dir_probs[0])
        prob_flat = float(dir_probs[1])
        prob_up = float(dir_probs[2])

        # Price interval
        p5_price = float(self._q_low_model.predict(x_input)[0])  # type: ignore[union-attr]
        p95_price = float(self._q_high_model.predict(x_input)[0])  # type: ignore[union-attr]

        inference_ms = (time.time() - t0) * 1000

        # Determine direction
        if prob_up >= prob_down and prob_up >= prob_flat:
            direction = "up"
            confidence = prob_up
        elif prob_down >= prob_up and prob_down >= prob_flat:
            direction = "down"
            confidence = prob_down
        else:
            direction = "flat"
            confidence = prob_flat

        current_price = context.cross_asset.es_price or 5400.0
        median = round((p5_price + p95_price) / 2, 2)

        # Step 3: GPT-4o synthesis
        forecast_text = self._synthesize(
            instrument=instrument,
            horizon_minutes=horizon_minutes,
            current_price=current_price,
            direction=direction,
            confidence=confidence,
            prob_up=prob_up,
            prob_down=prob_down,
            prob_flat=prob_flat,
            p5=p5_price,
            p95=p95_price,
            median=median,
            context=context,
        )

        meta = self._store.get_metadata(constants.ML_DIRECTION_MODEL_KEY) or {}

        duration = round(time.time() - pipeline_start_time, 1)

        return FastPathResult(
            forecast_id=forecast_id,
            instrument=instrument,
            forecast_horizon_minutes=horizon_minutes,
            current_price=current_price,
            prob_up=round(prob_up, 4),
            prob_down=round(prob_down, 4),
            prob_flat=round(prob_flat, 4),
            predicted_direction=direction,
            direction_confidence=round(confidence, 4),
            predicted_p5=round(p5_price, 2),
            predicted_p95=round(p95_price, 2),
            predicted_median=median,
            forecast_text=forecast_text,
            feature_count=self._extractor.feature_count,
            model_trained_at=meta.get("trained_at"),
            model_sample_size=meta.get("samples", 0),
            inference_ms=round(inference_ms, 1),
            pipeline_duration_seconds=duration,
            created_at=datetime.utcnow(),
        )

    def _load_models(self) -> None:
        """Load all three models from Redis."""
        try:
            self._dir_model = self._store.load_model(constants.ML_DIRECTION_MODEL_KEY)
            self._q_low_model = self._store.load_model(constants.ML_QUANTILE_LOW_KEY)
            self._q_high_model = self._store.load_model(constants.ML_QUANTILE_HIGH_KEY)

            if all(
                [
                    self._dir_model,
                    self._q_low_model,
                    self._q_high_model,
                ]
            ):
                self._models_loaded = True
                logger.info("Fast path models loaded from Redis")
            else:
                self._models_loaded = False
                logger.info("Fast path models not available in Redis")
        except Exception:
            logger.error("Failed to load fast path models", exc_info=True)
            self._models_loaded = False

    def _synthesize(self, **kwargs: object) -> str:
        """Generate natural language forecast from fast path results."""
        try:
            prompt = FAST_SYNTHESIS_PROMPT.format(
                instrument=kwargs["instrument"],
                horizon_minutes=kwargs["horizon_minutes"],
                current_price=kwargs["current_price"],
                direction=kwargs["direction"],
                confidence=kwargs["confidence"],
                prob_up=kwargs["prob_up"],
                prob_down=kwargs["prob_down"],
                prob_flat=kwargs["prob_flat"],
                p5=kwargs["p5"],
                p95=kwargs["p95"],
                median=kwargs["median"],
                vix=kwargs["context"].vix.spot or "N/A",  # type: ignore[union-attr]
                vix_regime=(
                    kwargs["context"].vix.regime.value  # type: ignore[union-attr]
                    if kwargs["context"].vix.regime  # type: ignore[union-attr]
                    else "unknown"
                ),
                fear_greed=kwargs["context"].fear_greed.value  # type: ignore[union-attr]
                or "N/A",
            )

            return self._llm.chat(
                system_prompt=prompt,
                user_message="Generate the forecast.",
                model=constants.SYNTHESIS_MODEL,
                temperature=0.3,
                max_tokens=300,
                timeout=15,
            )
        except Exception as e:
            logger.warning(f"Fast path synthesis failed: {e}")
            return (
                f"{kwargs['instrument']} is {kwargs['direction']} "
                f"with {kwargs['confidence']:.0%} confidence over "
                f"the next {kwargs['horizon_minutes']} minutes. "
                f"Expected range: "
                f"{kwargs['p5']:.2f}–{kwargs['p95']:.2f}."
            )

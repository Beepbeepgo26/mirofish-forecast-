"""Conformalized Quantile Regression — calibrates prediction intervals.

Uses LightGBM quantile regressors to learn conditional prediction intervals,
then applies conformal correction for distribution-free coverage guarantees.

Activates only after CALIBRATION_MIN_SAMPLES forecasts have been scored.
"""

import logging

import numpy as np

from mirofish_forecast.config import constants

logger = logging.getLogger(__name__)


class CQRCalibrator:
    """Conformalized Quantile Regression using LightGBM."""

    def __init__(self) -> None:
        self._models: dict[float, object] = {}  # quantile -> trained LightGBM model
        self._conformal_scores: np.ndarray | None = None
        self._conformal_threshold: float = 0.0
        self._is_fitted: bool = False
        self._sample_size: int = 0
        self._observed_coverage: float = 0.0

    @property
    def is_fitted(self) -> bool:
        """Whether the CQR model has been successfully fitted."""
        return self._is_fitted

    @property
    def sample_size(self) -> int:
        """Number of samples used for training."""
        return self._sample_size

    @property
    def observed_coverage(self) -> float:
        """Observed coverage on calibration set."""
        return self._observed_coverage

    def fit(self, features: list[dict]) -> bool:
        """Train CQR model on historical forecast-outcome pairs.

        Args:
            features: List of dicts from ForecastTracker.get_calibration_features()

        Returns:
            True if fitting succeeded, False if insufficient data
        """
        if len(features) < constants.CALIBRATION_MIN_SAMPLES:
            logger.info(
                f"Insufficient data for CQR: {len(features)}/{constants.CALIBRATION_MIN_SAMPLES}"
            )
            return False

        try:
            import lightgbm as lgb

            # Prepare arrays
            feature_cols = [
                "vix",
                "fear_greed",
                "agent_disagreement",
                "sim_success_rate",
                "predicted_std",
                "horizon_minutes",
                "predicted_prob_up",
                "predicted_prob_down",
            ]

            x_array = np.array(
                [[f.get(col, 0) or 0 for col in feature_cols] for f in features],
                dtype=np.float32,
            )
            y_residual = np.array(
                [f["residual"] for f in features], dtype=np.float32
            )

            # Split: training + calibration
            n = len(features)
            n_cal = max(int(n * constants.CQR_CALIBRATION_SPLIT), 20)
            n_train = n - n_cal

            x_train, x_cal = x_array[:n_train], x_array[n_train:]
            y_train, y_cal = y_residual[:n_train], y_residual[n_train:]

            # Train quantile regressors
            self._models = {}
            for q in constants.CQR_QUANTILES:
                params = {
                    "objective": "quantile",
                    "alpha": q,
                    "num_leaves": 31,
                    "learning_rate": 0.05,
                    "n_estimators": 100,
                    "verbose": -1,
                }
                model = lgb.LGBMRegressor(**params)
                model.fit(x_train, y_train)
                self._models[q] = model

            # Compute conformal scores on calibration set
            q_low = self._models[constants.CQR_QUANTILES[0]].predict(x_cal)
            q_high = self._models[constants.CQR_QUANTILES[-1]].predict(x_cal)

            # Conformity score = max(q_low - y, y - q_high)
            scores = np.maximum(q_low - y_cal, y_cal - q_high)
            self._conformal_scores = np.sort(scores)

            # Threshold at (1 - alpha) quantile
            idx = int(np.ceil((1 - constants.CQR_ALPHA) * (len(scores) + 1))) - 1
            idx = min(idx, len(scores) - 1)
            self._conformal_threshold = float(self._conformal_scores[idx])

            # Compute observed coverage on calibration set
            adjusted_low = q_low - self._conformal_threshold
            adjusted_high = q_high + self._conformal_threshold
            coverage = np.mean((y_cal >= adjusted_low) & (y_cal <= adjusted_high))
            self._observed_coverage = float(coverage)

            self._is_fitted = True
            self._sample_size = n

            logger.info(
                f"CQR fitted: {n} samples, threshold={self._conformal_threshold:.4f}, "
                f"coverage={self._observed_coverage:.3f}"
            )
            return True

        except Exception:
            logger.error("CQR fitting failed", exc_info=True)
            self._is_fitted = False
            return False

    def predict_intervals(
        self,
        vix: float,
        fear_greed: float,
        agent_disagreement: float,
        sim_success_rate: float,
        predicted_std: float,
        horizon_minutes: int,
        predicted_prob_up: float,
        predicted_prob_down: float,
    ) -> dict[float, float]:
        """Predict calibrated quantile adjustments for a new forecast.

        Returns:
            Dict mapping quantile level to residual adjustment value.
            Add these to the raw predicted quantiles for calibrated intervals.
        """
        if not self._is_fitted:
            return {q: 0.0 for q in constants.CQR_QUANTILES}

        x_input = np.array(
            [
                [
                    vix or 0,
                    fear_greed or 0,
                    agent_disagreement,
                    sim_success_rate,
                    predicted_std,
                    horizon_minutes,
                    predicted_prob_up,
                    predicted_prob_down,
                ]
            ],
            dtype=np.float32,
        )

        adjustments: dict[float, float] = {}
        for q in constants.CQR_QUANTILES:
            pred = float(self._models[q].predict(x_input)[0])
            # Apply conformal correction to extreme quantiles
            if q <= 0.5:
                adjustments[q] = pred - self._conformal_threshold
            else:
                adjustments[q] = pred + self._conformal_threshold

        return adjustments

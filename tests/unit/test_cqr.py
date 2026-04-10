"""Test CQR calibrator."""

import numpy as np

from mirofish_forecast.calibration.cqr import CQRCalibrator


class TestCQRCalibrator:
    def test_not_fitted_returns_zero_adjustments(self) -> None:
        cqr = CQRCalibrator()
        assert not cqr.is_fitted
        adjustments = cqr.predict_intervals(
            vix=22.0,
            fear_greed=38.0,
            agent_disagreement=5.0,
            sim_success_rate=0.95,
            predicted_std=10.0,
            horizon_minutes=120,
            predicted_prob_up=0.6,
            predicted_prob_down=0.3,
        )
        assert all(v == 0.0 for v in adjustments.values())

    def test_fit_requires_minimum_samples(self) -> None:
        cqr = CQRCalibrator()
        features = [
            {
                "residual": 0,
                "vix": 20,
                "fear_greed": 50,
                "agent_disagreement": 5,
                "sim_success_rate": 0.9,
                "predicted_std": 10,
                "horizon_minutes": 120,
                "predicted_prob_up": 0.5,
                "predicted_prob_down": 0.3,
            }
        ] * 50
        assert not cqr.fit(features)  # 50 < 200 minimum

    def test_fit_succeeds_with_enough_data(self) -> None:
        cqr = CQRCalibrator()
        rng = np.random.default_rng(42)
        features = []
        for _ in range(250):
            features.append(
                {
                    "residual": float(rng.normal(0, 5)),
                    "vix": float(rng.uniform(15, 35)),
                    "fear_greed": float(rng.uniform(10, 90)),
                    "agent_disagreement": float(rng.uniform(2, 15)),
                    "sim_success_rate": float(rng.uniform(0.7, 1.0)),
                    "predicted_std": float(rng.uniform(5, 20)),
                    "horizon_minutes": int(rng.choice([60, 120, 240])),
                    "predicted_prob_up": float(rng.uniform(0.2, 0.8)),
                    "predicted_prob_down": float(rng.uniform(0.1, 0.5)),
                }
            )
        assert cqr.fit(features)
        assert cqr.is_fitted
        assert cqr.sample_size == 250
        assert 0.5 < cqr.observed_coverage < 1.0


class TestCQRPrediction:
    def test_fitted_model_returns_nonzero_adjustments(self) -> None:
        cqr = CQRCalibrator()
        rng = np.random.default_rng(42)
        features = []
        for _ in range(250):
            features.append(
                {
                    "residual": float(rng.normal(0, 5)),
                    "vix": float(rng.uniform(15, 35)),
                    "fear_greed": float(rng.uniform(10, 90)),
                    "agent_disagreement": float(rng.uniform(2, 15)),
                    "sim_success_rate": float(rng.uniform(0.7, 1.0)),
                    "predicted_std": float(rng.uniform(5, 20)),
                    "horizon_minutes": 120,
                    "predicted_prob_up": float(rng.uniform(0.2, 0.8)),
                    "predicted_prob_down": float(rng.uniform(0.1, 0.5)),
                }
            )
        cqr.fit(features)

        adjustments = cqr.predict_intervals(
            vix=25.0,
            fear_greed=30.0,
            agent_disagreement=8.0,
            sim_success_rate=0.92,
            predicted_std=12.0,
            horizon_minutes=120,
            predicted_prob_up=0.55,
            predicted_prob_down=0.35,
        )

        # Should have adjustments for each quantile
        assert len(adjustments) == 5
        # Lower quantile adjustments should be less than upper
        assert adjustments[0.05] < adjustments[0.95]

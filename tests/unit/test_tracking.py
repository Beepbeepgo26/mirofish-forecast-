"""Test forecast tracking."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from mirofish_forecast.calibration.tracking import ForecastTracker
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.models.forecast import (
    ForecastResult,
    ForecastTracking,
    ProbabilityDistribution,
)


def _make_forecast(
    forecast_id: str = "test123",
    current_price: float = 5420.0,
    median: float = 5425.0,
) -> ForecastResult:
    return ForecastResult(
        forecast_id=forecast_id,
        instrument="ES",
        forecast_horizon_minutes=120,
        current_price=current_price,
        forecast_text="Test forecast",
        distribution=ProbabilityDistribution(
            median=median,
            mean=median,
            std_dev=10.0,
            percentile_5=current_price - 15,
            percentile_25=current_price - 5,
            percentile_75=current_price + 5,
            percentile_95=current_price + 15,
            skewness=0.1,
            prob_up=0.6,
            prob_down=0.3,
            prob_flat=0.1,
        ),
        total_simulations=100,
        successful_simulations=95,
        sim_preset="quick",
        created_at=datetime.utcnow(),
        pipeline_duration_seconds=90.0,
    )


@pytest.fixture
def _patch_cache(mock_cache: MagicMock):
    """Patch CacheClient constructor to return the mock_cache fixture."""
    with patch.object(CacheClient, "__init__", lambda self, s: None):
        with patch.object(CacheClient, "get", mock_cache.get):
            with patch.object(CacheClient, "set", mock_cache.set):
                yield mock_cache


class TestStoreAndRetrieve:
    def test_store_forecast(self, mock_settings, mock_cache: MagicMock, _patch_cache) -> None:
        tracker = ForecastTracker(mock_settings)
        forecast = _make_forecast()
        tracking = tracker.store_forecast(forecast, vix_at_forecast=22.3)

        assert tracking.forecast_id == "test123"
        assert tracking.current_price == 5420.0
        assert tracking.predicted_median == 5425.0
        assert tracking.vix_at_forecast == 22.3
        assert not tracking.outcome_checked
        mock_cache.set.assert_called()


class TestCheckOutcome:
    def test_too_early(self, mock_settings, mock_cache: MagicMock, _patch_cache) -> None:
        """Should not check if horizon hasn't elapsed."""
        tracking = ForecastTracking(
            forecast_id="test",
            instrument="ES",
            forecast_horizon_minutes=120,
            created_at=datetime.utcnow(),
            current_price=5420.0,
            predicted_median=5425.0,
            predicted_p5=5405.0,
            predicted_p25=5415.0,
            predicted_p75=5435.0,
            predicted_p95=5445.0,
            predicted_prob_up=0.6,
            predicted_prob_down=0.3,
            predicted_prob_flat=0.1,
        )
        mock_cache.get.return_value = tracking.model_dump_json()

        tracker = ForecastTracker(mock_settings)
        result = tracker.check_outcome("test")

        assert result is not None
        assert not result.outcome_checked

    def test_scores_correctly(self, mock_settings, mock_cache: MagicMock, _patch_cache) -> None:
        """Should correctly score when horizon has elapsed."""
        import pandas as pd

        old_time = datetime.utcnow() - timedelta(hours=3)
        tracking = ForecastTracking(
            forecast_id="test",
            instrument="ES",
            forecast_horizon_minutes=120,
            created_at=old_time,
            current_price=5420.0,
            predicted_median=5425.0,
            predicted_p5=5405.0,
            predicted_p25=5415.0,
            predicted_p75=5435.0,
            predicted_p95=5445.0,
            predicted_prob_up=0.6,
            predicted_prob_down=0.3,
            predicted_prob_flat=0.1,
        )
        mock_cache.get.return_value = tracking.model_dump_json()

        # Mock yf.download to return a bar near the target time
        target_time = old_time + timedelta(minutes=120)
        mock_df = pd.DataFrame(
            {"Close": [5430.0]},
            index=pd.DatetimeIndex([target_time]),
        )

        with patch("mirofish_forecast.calibration.tracking.yf") as mock_yf:
            mock_yf.download.return_value = mock_df
            tracker = ForecastTracker(mock_settings)
            result = tracker.check_outcome("test")

        assert result is not None
        assert result.outcome_checked
        assert result.actual_price == 5430.0
        assert result.actual_direction == "up"
        assert result.direction_correct is True
        assert result.p50_hit is True
        assert result.p90_hit is True


class TestGetCalibrationFeatures:
    def test_extracts_features(self, mock_settings, mock_cache: MagicMock, _patch_cache) -> None:
        scored = ForecastTracking(
            forecast_id="test",
            instrument="ES",
            forecast_horizon_minutes=120,
            created_at=datetime.utcnow() - timedelta(hours=3),
            current_price=5420.0,
            predicted_median=5425.0,
            predicted_p5=5405.0,
            predicted_p25=5415.0,
            predicted_p75=5435.0,
            predicted_p95=5445.0,
            predicted_prob_up=0.6,
            predicted_prob_down=0.3,
            predicted_prob_flat=0.1,
            vix_at_forecast=22.3,
            fear_greed_at_forecast=38.0,
            agent_disagreement=5.5,
            actual_price=5430.0,
            actual_direction="up",
            absolute_error=5.0,
            outcome_checked=True,
        )
        mock_cache.get.side_effect = [
            json.dumps(["test"]),  # index
            scored.model_dump_json(),  # record
        ]

        tracker = ForecastTracker(mock_settings)
        features = tracker.get_calibration_features()

        assert len(features) == 1
        assert features[0]["vix"] == 22.3
        assert features[0]["residual"] == 5.0  # 5430 - 5425

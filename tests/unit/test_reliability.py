"""Test reliability diagram and calibration metrics."""

from datetime import datetime, timedelta

from mirofish_forecast.calibration.reliability import (
    compute_calibration_summary,
    compute_ece,
    compute_interval_coverage,
    compute_reliability_diagram_data,
)
from mirofish_forecast.models.forecast import ForecastTracking


def _make_scored(
    prob_up: float = 0.6,
    prob_down: float = 0.3,
    prob_flat: float = 0.1,
    direction_correct: bool = True,
    p50_hit: bool = True,
    p90_hit: bool = True,
) -> ForecastTracking:
    return ForecastTracking(
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
        predicted_prob_up=prob_up,
        predicted_prob_down=prob_down,
        predicted_prob_flat=prob_flat,
        actual_price=5430.0,
        actual_direction="up",
        direction_correct=direction_correct,
        absolute_error=5.0,
        outcome_checked=True,
        p50_hit=p50_hit,
        p90_hit=p90_hit,
    )


class TestECE:
    def test_perfect_calibration_low_ece(self) -> None:
        """All correct at 60% confidence should give non-zero ECE."""
        forecasts = [_make_scored(prob_up=0.6, direction_correct=True) for _ in range(50)]
        ece = compute_ece(forecasts)
        assert ece > 0  # Not perfectly calibrated (100% accuracy at 60% conf)

    def test_empty_returns_zero(self) -> None:
        assert compute_ece([]) == 0.0


class TestIntervalCoverage:
    def test_all_covered(self) -> None:
        forecasts = [_make_scored(p50_hit=True, p90_hit=True) for _ in range(20)]
        cov = compute_interval_coverage(forecasts)
        assert cov["p50_coverage"] == 1.0
        assert cov["p90_coverage"] == 1.0

    def test_partial_coverage(self) -> None:
        forecasts = [_make_scored(p50_hit=True, p90_hit=True) for _ in range(8)] + [
            _make_scored(p50_hit=False, p90_hit=True) for _ in range(2)
        ]
        cov = compute_interval_coverage(forecasts)
        assert cov["p50_coverage"] == 0.8
        assert cov["p90_coverage"] == 1.0


class TestReliabilityDiagram:
    def test_returns_data_with_enough_samples(self) -> None:
        forecasts = [_make_scored() for _ in range(20)]
        data = compute_reliability_diagram_data(forecasts)
        assert len(data) > 0
        assert "mean_predicted" in data[0]
        assert "mean_actual" in data[0]

    def test_empty_returns_empty(self) -> None:
        assert compute_reliability_diagram_data([]) == []


class TestCalibrationSummary:
    def test_summary_with_scored(self) -> None:
        forecasts = [_make_scored(direction_correct=True) for _ in range(15)]
        forecasts += [_make_scored(direction_correct=False) for _ in range(5)]
        summary = compute_calibration_summary(forecasts)

        assert summary["scored_forecasts"] == 20
        assert summary["direction_accuracy"] == 0.75
        assert "ece" in summary

    def test_summary_empty(self) -> None:
        summary = compute_calibration_summary([])
        assert summary["scored_forecasts"] == 0
        assert not summary["calibration_ready"]

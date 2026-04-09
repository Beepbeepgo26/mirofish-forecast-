"""Test forecast Pydantic models."""

from datetime import datetime

from mirofish_forecast.models.forecast import (
    ForecastResult,
    ProbabilityDistribution,
    SimulationResult,
)


class TestSimulationResult:
    def test_valid_creation(self):
        r = SimulationResult(
            sim_id=0,
            seed=12345,
            temperature=0.7,
            final_price=5425.0,
            success=True,
        )
        assert r.final_price == 5425.0

    def test_failed_simulation(self):
        r = SimulationResult(
            sim_id=1,
            seed=99999,
            temperature=0.5,
            final_price=5400.0,
            success=False,
            error="Timeout",
        )
        assert not r.success


class TestProbabilityDistribution:
    def test_valid_creation(self):
        d = ProbabilityDistribution(
            median=5420.0,
            mean=5418.5,
            std_dev=15.3,
            percentile_5=5390.0,
            percentile_25=5405.0,
            percentile_75=5435.0,
            percentile_95=5450.0,
            skewness=-0.2,
            prob_up=0.55,
            prob_down=0.35,
            prob_flat=0.10,
        )
        assert d.median == 5420.0


class TestForecastResult:
    def test_serialization_roundtrip(self):
        f = ForecastResult(
            forecast_id="test123",
            instrument="ES",
            forecast_horizon_minutes=120,
            current_price=5420.0,
            forecast_text="ES is likely to trade between 5400-5440.",
            distribution=ProbabilityDistribution(
                median=5420.0,
                mean=5418.5,
                std_dev=15.3,
                percentile_5=5390.0,
                percentile_25=5405.0,
                percentile_75=5435.0,
                percentile_95=5450.0,
                skewness=-0.2,
                prob_up=0.55,
                prob_down=0.35,
                prob_flat=0.10,
            ),
            total_simulations=200,
            successful_simulations=185,
            sim_preset="standard",
            created_at=datetime.utcnow(),
            pipeline_duration_seconds=120.5,
        )
        json_str = f.model_dump_json()
        restored = ForecastResult.model_validate_json(json_str)
        assert restored.forecast_id == "test123"
        assert restored.distribution.median == 5420.0

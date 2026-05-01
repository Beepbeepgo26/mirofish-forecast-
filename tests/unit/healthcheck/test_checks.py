"""Unit tests for healthcheck check functions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from mirofish_forecast.healthcheck.checks import (
    CheckResult,
    confidence_filtered_pct_sane,
    direction_model_accuracy_sane,
    direction_model_fresh,
    direction_model_mode_binary,
    direction_samples_sufficient,
    fast_forecast_reachable,
    hybrid_agents_firing,
    last_train_status_complete,
    live_writer_bars_increasing,
    live_writer_no_errors,
    market_snapshot_reachable,
    market_snapshot_uses_databento,
    ml_status_reachable,
    quantile_high_coverage_sane,
)


# --- Helpers ---


def _ml_status(
    trained_at: str | None = None,
    accuracy: float = 0.52,
    mode: str = "binary",
    conf_pct: float = 75.0,
    samples: int = 2500,
    train_status: str = "complete",
    coverage: float = 0.90,
) -> dict:
    """Build a mock /api/ml/status response."""
    return {
        "direction_model": {
            "trained_at": trained_at or datetime.now(timezone.utc).isoformat(),
            "accuracy": accuracy,
            "mode": mode,
            "confidence_filtered_pct": conf_pct,
            "direction_samples": samples,
        },
        "last_train_status": train_status,
        "models_available": True,
        "quantile_high_model": {"coverage": coverage},
    }


# --- Service Reachability ---


class TestMLStatusReachable:
    @patch("mirofish_forecast.healthcheck.checks._get_json")
    def test_pass(self, mock_get: MagicMock) -> None:
        mock_get.return_value = (200, {"models_available": True})
        result = ml_status_reachable()
        assert result.status == "pass"

    @patch("mirofish_forecast.healthcheck.checks._get_json")
    def test_fail_500(self, mock_get: MagicMock) -> None:
        mock_get.return_value = (500, {})
        result = ml_status_reachable()
        assert result.status == "fail"


class TestMarketSnapshotReachable:
    @patch("mirofish_forecast.healthcheck.checks._get_json")
    def test_pass(self, mock_get: MagicMock) -> None:
        mock_get.return_value = (200, {"source": "databento"})
        result = market_snapshot_reachable()
        assert result.status == "pass"

    @patch("mirofish_forecast.healthcheck.checks._get_json")
    def test_fail(self, mock_get: MagicMock) -> None:
        mock_get.return_value = (503, {})
        result = market_snapshot_reachable()
        assert result.status == "fail"


class TestFastForecastReachable:
    @patch("mirofish_forecast.healthcheck.checks._get_json")
    def test_pass(self, mock_get: MagicMock) -> None:
        mock_get.return_value = (200, {"forecast_id": "abc"})
        result = fast_forecast_reachable()
        assert result.status == "pass"

    @patch("mirofish_forecast.healthcheck.checks._get_json")
    def test_fail(self, mock_get: MagicMock) -> None:
        mock_get.return_value = (500, {})
        result = fast_forecast_reachable()
        assert result.status == "fail"


# --- Model Health ---


class TestDirectionModelFresh:
    def test_pass_recent(self) -> None:
        result = direction_model_fresh(_ml_status())
        assert result.status == "pass"

    def test_warn_10_days(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        result = direction_model_fresh(_ml_status(trained_at=old))
        assert result.status == "warn"

    def test_fail_20_days(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        result = direction_model_fresh(_ml_status(trained_at=old))
        assert result.status == "fail"

    def test_fail_missing(self) -> None:
        result = direction_model_fresh({"direction_model": {}})
        assert result.status == "fail"


class TestDirectionModelAccuracy:
    def test_pass_normal(self) -> None:
        result = direction_model_accuracy_sane(_ml_status(accuracy=0.52))
        assert result.status == "pass"

    def test_warn_high(self) -> None:
        result = direction_model_accuracy_sane(_ml_status(accuracy=0.65))
        assert result.status == "warn"
        assert "leakage" in result.message

    def test_warn_low(self) -> None:
        result = direction_model_accuracy_sane(_ml_status(accuracy=0.42))
        assert result.status == "warn"
        assert "degradation" in result.message

    def test_fail_missing(self) -> None:
        result = direction_model_accuracy_sane({"direction_model": {}})
        assert result.status == "fail"


class TestDirectionModelModeBinary:
    def test_pass(self) -> None:
        result = direction_model_mode_binary(_ml_status(mode="binary"))
        assert result.status == "pass"

    def test_fail_multiclass(self) -> None:
        result = direction_model_mode_binary(_ml_status(mode="multiclass"))
        assert result.status == "fail"


class TestConfidenceFilteredPct:
    def test_pass(self) -> None:
        result = confidence_filtered_pct_sane(_ml_status(conf_pct=75.0))
        assert result.status == "pass"

    def test_warn_too_low(self) -> None:
        result = confidence_filtered_pct_sane(_ml_status(conf_pct=15.0))
        assert result.status == "warn"

    def test_warn_too_high(self) -> None:
        result = confidence_filtered_pct_sane(_ml_status(conf_pct=99.0))
        assert result.status == "warn"


class TestDirectionSamplesSufficient:
    def test_pass(self) -> None:
        result = direction_samples_sufficient(_ml_status(samples=3000))
        assert result.status == "pass"

    def test_warn_low(self) -> None:
        result = direction_samples_sufficient(_ml_status(samples=500))
        assert result.status == "warn"


class TestLastTrainStatusComplete:
    def test_pass(self) -> None:
        result = last_train_status_complete(_ml_status(train_status="complete"))
        assert result.status == "pass"

    def test_fail(self) -> None:
        result = last_train_status_complete(_ml_status(train_status="failed:no_data"))
        assert result.status == "fail"


class TestQuantileHighCoverage:
    def test_pass(self) -> None:
        result = quantile_high_coverage_sane(_ml_status(coverage=0.90))
        assert result.status == "pass"

    def test_warn_low(self) -> None:
        result = quantile_high_coverage_sane(_ml_status(coverage=0.50))
        assert result.status == "warn"


# --- Data Source ---


class TestMarketSnapshotDatabento:
    def test_pass(self) -> None:
        result = market_snapshot_uses_databento({"source": "databento"})
        assert result.status == "pass"

    def test_warn_fallback(self) -> None:
        result = market_snapshot_uses_databento({"source": "yfinance"})
        assert result.status == "warn"


# --- Live Writer ---


class TestLiveWriterNoErrors:
    @patch("subprocess.run")
    def test_pass_no_errors(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"textPayload": "INFO Bars written: 5000"}]',
        )
        result = live_writer_no_errors()
        assert result.status == "pass"

    @patch("subprocess.run")
    def test_fail_errors(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"textPayload": "[ERROR] Authentication failed. Exception raised."}]',
        )
        result = live_writer_no_errors()
        assert result.status == "fail"

    @patch("subprocess.run")
    def test_warn_gcloud_fails(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="gcloud error")
        result = live_writer_no_errors()
        assert result.status == "warn"


class TestLiveWriterBarsIncreasing:
    @patch("subprocess.run")
    def test_pass_bars_found(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='[{"textPayload": "2026-05-01 08:00:00 [INFO] Bars written: 12000 | Latest NQ: 27400"}]',
        )
        result = live_writer_bars_increasing()
        # May be pass or skipped on weekend
        assert result.status in ("pass", "pass")

    @patch("subprocess.run")
    def test_fail_no_entries(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="[]")
        result = live_writer_bars_increasing()
        # Fail on weekday, pass on weekend
        if result.value == "weekend":
            assert result.status == "pass"
        else:
            assert result.status == "fail"


# --- Hybrid Agents ---


class TestHybridAgentsFiring:
    def test_pass_terms_present(self) -> None:
        result = hybrid_agents_firing({
            "institutional_reasoning": "VWAP at 5800, signal score 72",
            "forecast_text": "Based on day type analysis",
        })
        assert result.status == "pass"

    def test_fail_no_terms(self) -> None:
        result = hybrid_agents_firing({
            "institutional_reasoning": "The market looks bullish",
            "forecast_text": "Price may go up",
        })
        assert result.status == "fail"

    def test_pass_multiple_fields(self) -> None:
        result = hybrid_agents_firing({
            "market_maker_reasoning": "GEX near PDH level with ONH resistance",
            "retail_reasoning": "Retail crowd is buying near IB high",
        })
        assert result.status == "pass"


# --- Safe Check Decorator ---


class TestSafeCheckDecorator:
    def test_exception_becomes_fail(self) -> None:
        """Verify that _safe_check catches exceptions."""
        result = direction_model_fresh(None)  # type: ignore[arg-type]
        assert result.status == "fail"
        assert "exception" in result.value.lower() or "raised" in result.message.lower()

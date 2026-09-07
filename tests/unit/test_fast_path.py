"""Test the LightGBM fast path — the live trading surface must fail closed on a missing price."""

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mirofish_forecast.exceptions import MissingMarketDataError
from mirofish_forecast.ml.fast_path import FastPathRunner
from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
)


def _make_context(es_price: float | None) -> MarketContext:
    return MarketContext(
        macro=MacroIndicators(fed_funds_rate=5.25),
        vix=VIXData(spot=22.3),
        cross_asset=CrossAssetSnapshot(es_price=es_price),
        fear_greed=FearGreedData(value=38.0, description="Fear"),
        internals=MarketInternals(),
        assembled_at=datetime.utcnow(),
    )


def _make_runner(mock_settings) -> FastPathRunner:
    """FastPathRunner with loaded mock models and no external clients."""
    with (
        patch("mirofish_forecast.ml.fast_path.CacheClient"),
        patch("mirofish_forecast.ml.fast_path.ModelStore"),
        patch("mirofish_forecast.ml.fast_path.LLMClient"),
    ):
        runner = FastPathRunner(mock_settings)

    runner._models_loaded = True
    runner._dir_model = MagicMock()
    runner._dir_model.predict_proba.return_value = np.array([[0.4, 0.6]])
    runner._q_low_model = MagicMock()
    runner._q_low_model.predict.return_value = np.array([5400.0])
    runner._q_high_model = MagicMock()
    runner._q_high_model.predict.return_value = np.array([5440.0])
    runner._extractor = MagicMock()
    runner._extractor.extract.return_value = np.zeros(30)
    runner._extractor.feature_count = 30
    runner._store.get_metadata.return_value = {}
    return runner


def _run(runner: FastPathRunner, context: MarketContext):
    return runner.run(
        context=context,
        ohlcv_bars=[],
        instrument="ES",
        horizon_minutes=30,
        forecast_id="test_fast",
        pipeline_start_time=time.time(),
    )


class TestFastPathFailsClosed:
    def test_run_refuses_when_es_price_missing(self, mock_settings):
        """Site fast_path.run: no live ES price -> raise, never a placeholder, no synthesis call."""
        runner = _make_runner(mock_settings)

        with pytest.raises(
            MissingMarketDataError, match=r"cross_asset\.es_price missing in fast_path\.run"
        ):
            _run(runner, _make_context(es_price=None))

        runner._llm.chat.assert_not_called()

    def test_run_uses_live_es_price(self, mock_settings):
        """With a live price present, the result carries that exact price."""
        runner = _make_runner(mock_settings)

        with patch.object(runner, "_synthesize", return_value="Fast forecast text."):
            result = _run(runner, _make_context(es_price=5420.0))

        assert result.current_price == 5420.0
        assert result.forecast_text == "Fast forecast text."

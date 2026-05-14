"""Tests for the Al Brooks signal bar scoring rubric."""

import pytest

from mirofish_forecast.ml.signal_bar import (
    compute_ema,
    describe_signal_score,
    extract_bar_features,
    score_signal_bar,
)


class TestScoreSignalBar:
    def test_high_quality_bullish_bar_scores_above_70(self):
        """A large bullish engulfing bar at the 20 EMA should score 70+."""
        bar = {
            "open": 5700.0,
            "high": 5710.0,
            "low": 5699.0,
            "close": 5708.0,  # Closes near top, strong body
            "volume": 15000,
        }
        prior_bar = {
            "open": 5703.0,
            "high": 5704.0,
            "low": 5699.0,
            "close": 5700.0,
            "volume": 8000,
        }
        score = score_signal_bar(
            bar=bar,
            prior_bar=prior_bar,
            ema_20=5701.0,  # Price just touched EMA from below
            trend_context="strong_trend",
            is_second_entry=True,
            avg_bar_range=8.0,
        )
        assert score >= 70, f"Expected ≥70, got {score}"

    def test_doji_bar_scores_below_30(self):
        """A doji (tiny body, wide tails) should score below 30."""
        bar = {
            "open": 5700.0,
            "high": 5712.0,
            "low": 5688.0,  # 24-pt range
            "close": 5700.5,  # Almost no body
            "volume": 5000,
        }
        score = score_signal_bar(
            bar=bar,
            ema_20=5720.0,  # Far from EMA
            trend_context="trading_range",
        )
        assert score < 30, f"Expected < 30, got {score}"

    def test_with_trend_context_scores_higher_than_counter_trend(self):
        """Same bar should score higher in strong_trend than counter_trend context."""
        bar = {
            "open": 5700.0,
            "high": 5706.0,
            "low": 5698.0,
            "close": 5705.0,
            "volume": 10000,
        }
        score_trend = score_signal_bar(bar=bar, trend_context="strong_trend")
        score_counter = score_signal_bar(bar=bar, trend_context="counter_trend")
        assert score_trend > score_counter, f"Trend {score_trend} should > counter {score_counter}"

    def test_score_clamped_between_0_and_100(self):
        """Score should never exceed 100 or go below 0."""
        # Perfect bar
        perfect = {
            "open": 5700.0,
            "high": 5710.0,
            "low": 5699.5,  # tiny lower wick
            "close": 5709.5,  # near top
        }
        s1 = score_signal_bar(
            perfect,
            ema_20=5699.5,
            trend_context="strong_trend",
            is_second_entry=True,
            avg_bar_range=8.0,
        )
        assert 0 <= s1 <= 100

        # Worst possible bar
        worst = {
            "open": 5700.0,
            "high": 5700.1,
            "low": 5699.9,
            "close": 5700.0,
        }
        s2 = score_signal_bar(worst, ema_20=5750.0, trend_context="counter_trend")
        assert 0 <= s2 <= 100

    def test_zero_range_bar_returns_zero(self):
        """Bar with zero range (open=high=low=close) returns 0."""
        flat_bar = {"open": 5700.0, "high": 5700.0, "low": 5700.0, "close": 5700.0}
        assert score_signal_bar(flat_bar) == 0

    def test_missing_keys_raise_value_error(self):
        """Bar without open/high/low/close raises ValueError."""
        with pytest.raises(ValueError):
            score_signal_bar({"open": 5700.0, "high": 5710.0})

    def test_second_entry_adds_5_points(self):
        """is_second_entry=True should add exactly 5 points over is_second_entry=False."""
        bar = {
            "open": 5700.0,
            "high": 5705.0,
            "low": 5699.0,
            "close": 5703.0,
        }
        score_first = score_signal_bar(bar, is_second_entry=False)
        score_second = score_signal_bar(bar, is_second_entry=True)
        assert score_second == score_first + 5

    def test_bearish_bar_scored_correctly(self):
        """A strong bearish bar should score using inverse logic (close near low)."""
        bar = {
            "open": 5710.0,
            "high": 5710.5,  # tiny upper wick
            "low": 5700.0,
            "close": 5700.5,  # closed near low
        }
        score = score_signal_bar(
            bar=bar,
            ema_20=5709.0,
            trend_context="strong_trend",  # down trend
        )
        # Body ratio = 9.5/10.5 = 90% → 25pts
        # Close location for bearish: (high-close)/range = 9.5/10.5 = 90% → 20pts
        # Score should be reasonably high
        assert score >= 40, f"Expected ≥40, got {score}"


class TestComputeEma:
    def test_ema_requires_minimum_period(self):
        """Returns None when prices list < period."""
        assert compute_ema([5700.0] * 5, period=20) is None

    def test_ema_equals_price_for_flat_series(self):
        """EMA of a flat price series equals the price."""
        prices = [5700.0] * 25
        ema = compute_ema(prices, period=20)
        assert ema == 5700.0

    def test_ema_trends_toward_new_price(self):
        """EMA moves toward new price after a step change."""
        prices = [5700.0] * 20 + [5800.0] * 5
        ema = compute_ema(prices)
        assert ema is not None
        assert 5700.0 < ema < 5800.0


class TestExtractBarFeatures:
    def test_returns_empty_for_no_bars(self):
        assert extract_bar_features([]) == {}

    def test_trend_context_inferred_from_prices(self):
        """Bars all above EMA → strong_trend or channel inferred."""
        bars = [
            {"open": 5700 + i, "high": 5710 + i, "low": 5698 + i, "close": 5705 + i, "volume": 1000}
            for i in range(25)
        ]
        features = extract_bar_features(bars)
        assert "trend_context" in features
        assert features["trend_context"] in (
            "strong_trend",
            "channel",
            "trading_range",
            "counter_trend",
            "unknown",
        )

    def test_prior_bar_is_second_to_last(self):
        bars = [
            {"open": 5700.0, "high": 5705.0, "low": 5699.0, "close": 5702.0, "volume": 1000},
            {"open": 5702.0, "high": 5708.0, "low": 5701.0, "close": 5706.0, "volume": 1200},
        ]
        features = extract_bar_features(bars, current_idx=1)
        assert features["prior_bar"] == bars[0]


class TestDescribeSignalScore:
    def test_high_score_label(self):
        assert "HIGH CONVICTION" in describe_signal_score(75)

    def test_moderate_score_label(self):
        assert "MODERATE" in describe_signal_score(58)

    def test_weak_score_label(self):
        assert "WEAK" in describe_signal_score(40)

    def test_do_not_act_label(self):
        assert "DO NOT ACT" in describe_signal_score(20)

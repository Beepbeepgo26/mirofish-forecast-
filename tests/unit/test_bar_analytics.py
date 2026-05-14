"""Test bar analytics computation."""

from __future__ import annotations

from mirofish_forecast.ml.signal_bar import compute_ema
from mirofish_forecast.services.bar_analytics import (
    _adr_pct_used,
    _classify_day_type,
    _count_consecutive,
    _determine_always_in,
    _empty_analytics,
    compute_bar_analytics,
    format_analytics_for_prompt,
)


def _make_bars(
    n: int,
    start_price: float = 5400.0,
    step: float = 1.0,
    start_time: int = 1700000000,
) -> list[dict]:
    """Generate n simple ascending bars for testing."""
    bars: list[dict] = []
    for i in range(n):
        c = start_price + i * step
        bars.append(
            {
                "time": start_time + i * 300,
                "open": c - 0.5,
                "high": c + 2,
                "low": c - 2,
                "close": c + 0.5,
                "volume": 10000,
            }
        )
    return bars


def _make_descending_bars(
    n: int,
    start_price: float = 5400.0,
    step: float = 1.0,
) -> list[dict]:
    """Generate n descending bars."""
    bars: list[dict] = []
    for i in range(n):
        c = start_price - i * step
        bars.append(
            {
                "time": 1700000000 + i * 300,
                "open": c + 0.5,
                "high": c + 2,
                "low": c - 2,
                "close": c - 0.5,
                "volume": 10000,
            }
        )
    return bars


class TestEMAComputation:
    """Test EMA via signal_bar.compute_ema (reused by bar_analytics)."""

    def test_ema_returns_value_with_sufficient_data(self) -> None:
        closes = [100.0 + i for i in range(30)]
        ema = compute_ema(closes, 20)
        assert ema is not None
        assert ema > 0

    def test_ema_trails_uptrend(self) -> None:
        closes = [100.0 + i for i in range(30)]
        ema = compute_ema(closes, 20)
        assert ema is not None
        assert ema < closes[-1]  # EMA trails in uptrend

    def test_ema_returns_none_insufficient_data(self) -> None:
        closes = [100.0 + i for i in range(5)]
        ema = compute_ema(closes, 20)
        assert ema is None


class TestSignalBarScore:
    """Test signal bar scoring via compute_bar_analytics."""

    def test_score_in_range(self) -> None:
        bars = _make_bars(30)
        result = compute_bar_analytics(bars)
        assert 0 <= result["signal_score"] <= 100

    def test_strong_bull_bar_scores_moderate_or_higher(self) -> None:
        bars = _make_bars(20)
        # Add a strong bull bar
        bars.append(
            {
                "time": bars[-1]["time"] + 300,
                "open": 5420.0,
                "high": 5428.0,
                "low": 5419.5,
                "close": 5427.5,
                "volume": 15000,
            }
        )
        result = compute_bar_analytics(bars)
        assert result["signal_score"] >= 40  # Should be at least moderate

    def test_doji_scores_low(self) -> None:
        bars = _make_bars(20)
        # Doji: open ≈ close
        bars.append(
            {
                "time": bars[-1]["time"] + 300,
                "open": 5420.0,
                "high": 5425.0,
                "low": 5415.0,
                "close": 5420.1,
                "volume": 10000,
            }
        )
        result = compute_bar_analytics(bars)
        assert result["signal_score"] < 50


class TestDayTypeClassification:
    """Test _classify_day_type."""

    def test_unknown_with_few_bars(self) -> None:
        bars = _make_bars(2)
        assert _classify_day_type(bars) == "unknown"

    def test_trading_range_with_middle_open(self) -> None:
        # Open in middle of range → trading range
        bars = _make_bars(15)
        # Override first bar to open mid-range
        mid = (bars[0]["low"] + bars[-1]["high"]) / 2
        bars[0] = {**bars[0], "open": mid}
        result = _classify_day_type(bars)
        assert result in ("trading_range", "spike_and_channel", "unknown")


class TestAlwaysInDirection:
    """Test _determine_always_in."""

    def test_neutral_with_insufficient_data(self) -> None:
        bars = _make_bars(5)
        assert _determine_always_in(bars, 5402.5) == "neutral"

    def test_long_in_uptrend(self) -> None:
        # 25 ascending bars, EMA well below close
        bars = _make_bars(25, step=2.0)
        ema = float(compute_ema([b["close"] for b in bars], 20) or 0)
        result = _determine_always_in(bars, ema)
        assert result == "long"

    def test_short_in_downtrend(self) -> None:
        bars = _make_descending_bars(25, step=2.0)
        ema = float(compute_ema([b["close"] for b in bars], 20) or 0)
        result = _determine_always_in(bars, ema)
        assert result == "short"


class TestConsecutiveBars:
    """Test _count_consecutive."""

    def test_ascending_streak(self) -> None:
        bars = _make_bars(10, step=1.0)
        result = _count_consecutive(bars)
        assert result > 0  # Positive = bullish

    def test_descending_streak(self) -> None:
        bars = _make_descending_bars(10, step=1.0)
        result = _count_consecutive(bars)
        assert result < 0  # Negative = bearish

    def test_single_bar(self) -> None:
        bars = _make_bars(1)
        assert _count_consecutive(bars) == 0


class TestADRPctUsed:
    """Test _adr_pct_used."""

    def test_zero_with_insufficient_data(self) -> None:
        bars = _make_bars(1)
        assert _adr_pct_used(bars) == 0.0


class TestComputeBarAnalytics:
    """Test the full compute_bar_analytics function."""

    def test_returns_all_fields(self) -> None:
        bars = _make_bars(50)
        result = compute_bar_analytics(bars)
        expected_keys = {
            "ema_20",
            "signal_score",
            "day_type",
            "always_in",
            "time_phase",
            "time_multiplier",
            "bar_number",
            "consecutive_trend_bars",
            "adr_pct_used",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_empty_bars_returns_empty_analytics(self) -> None:
        result = compute_bar_analytics([])
        assert result["signal_score"] == 0
        assert result["always_in"] == "neutral"
        assert result["day_type"] == "unknown"

    def test_few_bars_returns_empty_analytics(self) -> None:
        result = compute_bar_analytics(_make_bars(3))
        assert result["signal_score"] == 0
        assert result["always_in"] == "neutral"

    def test_ema_20_computed(self) -> None:
        bars = _make_bars(30)
        result = compute_bar_analytics(bars)
        assert result["ema_20"] > 0

    def test_time_multiplier_is_float(self) -> None:
        bars = _make_bars(30)
        result = compute_bar_analytics(bars)
        assert isinstance(result["time_multiplier"], float)
        assert 0.0 < result["time_multiplier"] <= 1.5


class TestFormatAnalytics:
    """Test format_analytics_for_prompt."""

    def test_format_contains_key_sections(self) -> None:
        analytics = compute_bar_analytics(_make_bars(30))
        text = format_analytics_for_prompt(analytics)
        assert "PRE-COMPUTED BAR ANALYTICS" in text
        assert "20-bar EMA" in text
        assert "Signal Bar Score" in text
        assert "Day Type" in text
        assert "Always-In Direction" in text
        assert "Time Phase" in text

    def test_format_empty_analytics(self) -> None:
        text = format_analytics_for_prompt(_empty_analytics())
        assert "Signal Bar Score: 0/100" in text
        assert "LOW" in text

    def test_high_score_label(self) -> None:
        analytics = _empty_analytics()
        analytics["signal_score"] = 75
        text = format_analytics_for_prompt(analytics)
        assert "HIGH CONVICTION" in text

    def test_moderate_score_label(self) -> None:
        analytics = _empty_analytics()
        analytics["signal_score"] = 55
        text = format_analytics_for_prompt(analytics)
        assert "MODERATE" in text

"""Comprehensive tests for session_levels.py."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from mirofish_forecast.data.session_levels import (
    _empty_levels,
    compute_session_levels,
    format_bars_for_agents,
    format_session_levels_text,
)

ET = ZoneInfo("America/New_York")


def _rth_bar(offset_bars: int, date_override: date | None = None) -> dict:
    """Make a synthetic 5-min bar at RTH open + offset_bars * 5min."""
    today = date_override or datetime.now(ET).date()
    base_dt = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET)
    ts = base_dt.timestamp() + offset_bars * 300  # 300s = 5 min
    price = 5000.0 + offset_bars
    return {
        "time": int(ts),
        "open": price,
        "high": price + 3.0,
        "low": price - 3.0,
        "close": price + 1.0,
        "volume": 500,
    }


def _overnight_bar(hour: int, minute: int = 0, date_override: date | None = None) -> dict:
    """Make a bar in the overnight session (before 9:30 AM ET or after 4 PM ET)."""
    today = date_override or datetime.now(ET).date()
    dt = datetime(today.year, today.month, today.day, hour, minute, tzinfo=ET)
    ts = dt.timestamp()
    return {
        "time": int(ts),
        "open": 4980.0,
        "high": 4990.0,
        "low": 4975.0,
        "close": 4985.0,
        "volume": 100,
    }


class TestComputeSessionLevels:
    def test_empty_returns_empty_levels(self):
        levels = compute_session_levels([])
        assert levels == _empty_levels()

    def test_too_few_bars_returns_empty_levels(self):
        bars = [_rth_bar(i) for i in range(5)]  # < 20 bars
        levels = compute_session_levels(bars)
        assert levels == _empty_levels()

    def test_today_rth_open_is_first_bar_open(self):
        bars = [_rth_bar(i) for i in range(20)]
        levels = compute_session_levels(bars)
        assert levels["today_rth_open"] == bars[0]["open"]

    def test_today_rth_high_is_max_high(self):
        bars = [_rth_bar(i) for i in range(20)]
        expected_high = max(b["high"] for b in bars)
        levels = compute_session_levels(bars)
        assert levels["today_rth_high"] == round(expected_high, 2)

    def test_today_rth_low_is_min_low(self):
        bars = [_rth_bar(i) for i in range(20)]
        expected_low = min(b["low"] for b in bars)
        levels = compute_session_levels(bars)
        assert levels["today_rth_low"] == round(expected_low, 2)

    def test_current_bar_number_equals_rth_bar_count(self):
        bars = [_rth_bar(i) for i in range(20)]
        levels = compute_session_levels(bars)
        assert levels["current_bar_number"] == 20

    def test_vwap_computed_from_rth_bars(self):
        bars = [_rth_bar(i) for i in range(20)]
        levels = compute_session_levels(bars)
        assert levels["vwap"] is not None
        # VWAP must be between today's high and low
        assert levels["today_rth_low"] <= levels["vwap"] <= levels["today_rth_high"]

    def test_vwap_upper_above_vwap(self):
        bars = [_rth_bar(i) for i in range(20)]
        levels = compute_session_levels(bars)
        assert levels["vwap_upper"] is not None
        assert levels["vwap_upper"] >= levels["vwap"]

    def test_vwap_lower_below_vwap(self):
        bars = [_rth_bar(i) for i in range(20)]
        levels = compute_session_levels(bars)
        assert levels["vwap_lower"] is not None
        assert levels["vwap_lower"] <= levels["vwap"]

    def test_vwap_flat_series_equals_typical_price(self):
        """For bars with constant prices, VWAP should equal the typical price."""
        today = datetime.now(ET).date()
        base_dt = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET)
        base_ts = base_dt.timestamp()
        bars = [
            {
                "time": int(base_ts + i * 300),
                "open": 5000.0,
                "high": 5010.0,
                "low": 4990.0,
                "close": 5005.0,
                "volume": 1000,
            }
            for i in range(20)
        ]
        levels = compute_session_levels(bars)
        expected_tp = (5010.0 + 4990.0 + 5005.0) / 3  # = 5001.67
        assert abs(levels["vwap"] - round(expected_tp, 2)) < 0.1

    def test_ib_high_from_first_12_bars(self):
        bars = [_rth_bar(i) for i in range(20)]
        ib_bars = bars[:12]
        expected_ib_high = max(b["high"] for b in ib_bars)
        levels = compute_session_levels(bars)
        assert levels["ib_high"] == round(expected_ib_high, 2)

    def test_ib_low_from_first_12_bars(self):
        bars = [_rth_bar(i) for i in range(20)]
        ib_bars = bars[:12]
        expected_ib_low = min(b["low"] for b in ib_bars)
        levels = compute_session_levels(bars)
        assert levels["ib_low"] == round(expected_ib_low, 2)

    def test_ib_range_equals_high_minus_low(self):
        bars = [_rth_bar(i) for i in range(20)]
        levels = compute_session_levels(bars)
        assert abs(levels["ib_range"] - (levels["ib_high"] - levels["ib_low"])) < 0.001

    def test_overnight_high_low_computed(self):
        today = datetime.now(ET).date()
        overnight_bars = [_overnight_bar(h, date_override=today) for h in [2, 3, 4]]
        rth_bars = [_rth_bar(i) for i in range(20)]
        all_bars = overnight_bars + rth_bars
        levels = compute_session_levels(all_bars)
        assert levels["overnight_high"] is not None
        assert levels["overnight_low"] is not None
        assert levels["overnight_high"] >= levels["overnight_low"]

    def test_no_today_rth_returns_none_levels(self):
        """If we only have overnight bars (not enough), levels should be None."""
        today = date.today()
        bars = [_overnight_bar(h, date_override=today) for h in range(2, 9)] * 3  # 21 bars
        levels = compute_session_levels(bars)
        # These bars land in overnight, not today_rth → today_rth fields = None
        assert levels["today_rth_open"] is None
        assert levels["vwap"] is None

    def test_graceful_error_returns_empty(self):
        """Passing malformed data shouldn't raise — should return empty levels."""
        bad_bars = [{"time": "not-a-number", "open": 5000} for _ in range(25)]
        levels = compute_session_levels(bad_bars)
        assert levels == _empty_levels()


class TestFormatSessionLevelsText:
    def _make_full_levels(self) -> dict:
        return {
            "prior_rth_high": 5080.50,
            "prior_rth_low": 5020.25,
            "prior_rth_close": 5055.00,
            "overnight_high": 5065.00,
            "overnight_low": 5040.00,
            "today_rth_open": 5050.00,
            "today_rth_high": 5070.00,
            "today_rth_low": 5035.00,
            "vwap": 5052.30,
            "vwap_upper": 5062.00,
            "vwap_lower": 5042.60,
            "ib_high": 5060.00,
            "ib_low": 5042.00,
            "ib_range": 18.00,
            "current_bar_number": 24,
        }

    def test_includes_prior_day_levels(self):
        text = format_session_levels_text(self._make_full_levels())
        assert "5080.50" in text
        assert "5020.25" in text
        assert "5055.00" in text

    def test_includes_overnight_high_low(self):
        text = format_session_levels_text(self._make_full_levels())
        assert "5065.00" in text
        assert "5040.00" in text

    def test_includes_vwap(self):
        text = format_session_levels_text(self._make_full_levels())
        assert "5052.30" in text

    def test_includes_initial_balance(self):
        text = format_session_levels_text(self._make_full_levels())
        assert "5060.00" in text
        assert "18.00" in text

    def test_includes_bar_number(self):
        text = format_session_levels_text(self._make_full_levels())
        assert "24" in text
        assert "78" in text

    def test_empty_levels_returns_not_available_message(self):
        text = format_session_levels_text(_empty_levels())
        assert "Not available" in text

    def test_partial_levels_does_not_crash(self):
        """Only some levels populated — should show what's available, skip Nones."""
        levels = _empty_levels()
        levels["vwap"] = 5050.00
        levels["vwap_upper"] = 5060.00
        levels["vwap_lower"] = 5040.00
        text = format_session_levels_text(levels)
        assert "5050.00" in text


class TestFormatBarsForAgents:
    def _make_bars(self, n: int = 10) -> list[dict]:
        today = datetime.now(ET).date()
        base_dt = datetime(today.year, today.month, today.day, 9, 30, tzinfo=ET)
        base_ts = base_dt.timestamp()
        bars = []
        for i in range(n):
            price = 5000.0 + i
            bars.append(
                {
                    "time": int(base_ts + i * 300),
                    "open": price,
                    "high": price + 3.0,
                    "low": price - 3.0,
                    "close": price + 1.5,  # bullish
                    "volume": 1000,
                }
            )
        return bars

    def test_empty_bars_returns_not_available(self):
        text = format_bars_for_agents([])
        assert "Not available" in text

    def test_bullish_bar_shows_up_arrow(self):
        bars = self._make_bars(5)
        text = format_bars_for_agents(bars)
        assert "▲" in text

    def test_respects_max_bars_limit(self):
        bars = self._make_bars(60)
        text = format_bars_for_agents(bars, max_bars=10)
        assert "10 bars" in text

    def test_shows_ohlcv_values(self):
        bars = [
            {
                "time": 1000,
                "open": 5000.00,
                "high": 5010.00,
                "low": 4995.00,
                "close": 5005.00,
                "volume": 1234,
            }
        ]
        text = format_bars_for_agents(bars)
        assert "5000.00" in text
        assert "5010.00" in text
        assert "4995.00" in text
        assert "5005.00" in text
        assert "1,234" in text

    def test_bearish_bar_shows_down_arrow(self):
        bars = [
            {
                "time": 1000,
                "open": 5010.00,
                "high": 5012.00,
                "low": 5000.00,
                "close": 5001.00,  # close < open → bearish
                "volume": 500,
            }
        ]
        text = format_bars_for_agents(bars)
        assert "▼" in text

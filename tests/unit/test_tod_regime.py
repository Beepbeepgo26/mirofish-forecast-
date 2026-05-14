"""Tests for the time-of-day regime classifier."""

from datetime import datetime
from zoneinfo import ZoneInfo

from mirofish_forecast.services.tod_regime import (
    TODRegime,
    format_tod_context,
    get_tod_regime,
)

ET = ZoneInfo("America/New_York")


def make_et(hour: int, minute: int = 0) -> datetime:
    """Create a today's ET datetime at the given hour:minute."""
    from datetime import date

    today = date.today()
    return datetime(today.year, today.month, today.day, hour, minute, tzinfo=ET)


class TestGetTodRegime:
    def test_opening_rotation(self):
        """9:30–10:29 should be OPENING_ROTATION."""
        regime, multiplier, _ = get_tod_regime(make_et(9, 30))
        assert regime == TODRegime.OPENING_ROTATION
        assert multiplier == 0.85

    def test_opening_rotation_end_boundary(self):
        """10:29 still in OPENING_ROTATION, 10:30 transitions."""
        regime, _, _ = get_tod_regime(make_et(10, 29))
        assert regime == TODRegime.OPENING_ROTATION

    def test_trend_establish(self):
        """10:30–11:29 should be TREND_ESTABLISH."""
        regime, multiplier, _ = get_tod_regime(make_et(10, 30))
        assert regime == TODRegime.TREND_ESTABLISH
        assert multiplier == 1.00

    def test_lunch_doldrums_low_multiplier(self):
        """11:30–13:29 should return 0.50 confidence multiplier."""
        regime, multiplier, notes = get_tod_regime(make_et(12, 30))
        assert regime == TODRegime.LUNCH_DOLDRUMS
        assert multiplier == 0.50
        assert "mean-reversion" in notes.lower()

    def test_lunch_doldrums_start_boundary(self):
        """11:30 exactly should enter LUNCH_DOLDRUMS."""
        regime, _, _ = get_tod_regime(make_et(11, 30))
        assert regime == TODRegime.LUNCH_DOLDRUMS

    def test_prime_breakout_window(self):
        """14:00–14:44 on non-FOMC day should be PRIME_BREAKOUT."""
        regime, multiplier, _ = get_tod_regime(make_et(14, 15), is_fomc_day=False)
        assert regime == TODRegime.PRIME_BREAKOUT
        assert multiplier == 1.10

    def test_fomc_window_overrides_prime_breakout(self):
        """14:00–14:44 on FOMC day should be FOMC_WINDOW with lower multiplier."""
        regime, multiplier, notes = get_tod_regime(make_et(14, 15), is_fomc_day=True)
        assert regime == TODRegime.FOMC_WINDOW
        assert multiplier == 0.40
        assert "spike" in notes.lower()

    def test_power_hour(self):
        """15:00–15:59 should be POWER_HOUR."""
        regime, multiplier, _ = get_tod_regime(make_et(15, 0))
        assert regime == TODRegime.POWER_HOUR
        assert multiplier == 1.05

    def test_power_hour_close_boundary(self):
        """15:59 still in POWER_HOUR."""
        regime, _, _ = get_tod_regime(make_et(15, 59))
        assert regime == TODRegime.POWER_HOUR

    def test_overnight_before_rth(self):
        """3:00 AM should be OVERNIGHT."""
        regime, multiplier, _ = get_tod_regime(make_et(3, 0))
        assert regime == TODRegime.OVERNIGHT
        assert multiplier == 0.70

    def test_overnight_after_rth(self):
        """16:00 (market close) should be OVERNIGHT."""
        regime, _, _ = get_tod_regime(make_et(16, 0))
        assert regime == TODRegime.OVERNIGHT

    def test_pre_breakout_window(self):
        """13:30–13:59 should be PRE_BREAKOUT."""
        regime, multiplier, _ = get_tod_regime(make_et(13, 45))
        assert regime == TODRegime.PRE_BREAKOUT

    def test_default_uses_current_time(self):
        """Calling get_tod_regime() with no args should return a valid regime."""
        regime, multiplier, notes = get_tod_regime()
        assert isinstance(regime, TODRegime)
        assert 0.0 <= multiplier <= 2.0
        assert isinstance(notes, str)
        assert len(notes) > 0


class TestFormatTodContext:
    def test_format_includes_regime_label(self):
        now = make_et(9, 45)
        text = format_tod_context(now=now)
        assert "Opening Rotation" in text

    def test_format_includes_multiplier(self):
        now = make_et(12, 0)
        text = format_tod_context(now=now)
        assert "50%" in text

    def test_fomc_warning_in_fomc_window(self):
        now = make_et(14, 5)
        text = format_tod_context(now=now, is_fomc_day=True)
        assert "40%" in text or "FOMC" in text

    def test_low_confidence_window_warning(self):
        """Lunch doldrums should trigger the low confidence warning."""
        now = make_et(12, 30)
        text = format_tod_context(now=now)
        assert "LOW CONFIDENCE WINDOW" in text

    def test_minutes_to_close_warning_at_30_min(self):
        """With 30 minutes to close, should show gamma/0DTE warning."""
        now = make_et(15, 30)
        text = format_tod_context(now=now, minutes_to_close=30)
        assert "30 minutes" in text

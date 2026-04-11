"""Test market session detection and temporal resolution."""

from datetime import datetime
from zoneinfo import ZoneInfo

from mirofish_forecast.services.session_context import (
    get_session_info,
    resolve_temporal_reference,
)

ET = ZoneInfo("America/New_York")


class TestSessionDetection:
    def test_rth_open(self) -> None:
        """10:30 AM ET on a Tuesday should be RTH."""
        now = datetime(2026, 4, 7, 10, 30, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_type == "rth"
        assert info.is_rth_open
        assert info.is_tradeable

    def test_pre_market(self) -> None:
        """8:30 AM ET on a Wednesday should be pre-market."""
        now = datetime(2026, 4, 8, 8, 30, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_type == "pre_market"
        assert not info.is_rth_open
        assert info.is_tradeable

    def test_overnight(self) -> None:
        """11:00 PM ET on a Monday should be overnight."""
        now = datetime(2026, 4, 6, 23, 0, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_type == "overnight"
        assert not info.is_rth_open
        assert info.is_tradeable

    def test_weekend_saturday(self) -> None:
        """Saturday should be closed."""
        now = datetime(2026, 4, 11, 12, 0, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_type == "closed"
        assert info.is_weekend
        assert not info.is_rth_open

    def test_post_market(self) -> None:
        """4:30 PM ET on a Thursday should be post-market."""
        now = datetime(2026, 4, 9, 16, 30, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_type == "post_market"
        assert not info.is_rth_open

    def test_minutes_to_close(self) -> None:
        """During RTH, should correctly compute minutes to close."""
        now = datetime(2026, 4, 7, 15, 0, tzinfo=ET)
        info = get_session_info(now)
        assert info.minutes_to_rth_close == 60

    def test_next_rth_open_from_weekend(self) -> None:
        """From Saturday, next RTH open should be Monday."""
        now = datetime(2026, 4, 11, 12, 0, tzinfo=ET)
        info = get_session_info(now)
        assert info.next_rth_open is not None
        assert "Monday" in info.next_rth_open

    def test_daily_halt(self) -> None:
        """5:30 PM ET on a weekday should be daily halt."""
        now = datetime(2026, 4, 7, 17, 30, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_type == "closed"
        assert not info.is_tradeable

    def test_session_label_rth(self) -> None:
        """RTH session should have 'RTH Open' label."""
        now = datetime(2026, 4, 7, 11, 0, tzinfo=ET)
        info = get_session_info(now)
        assert info.session_label == "RTH Open"

    def test_session_label_weekend(self) -> None:
        """Weekend should have 'Weekend' label."""
        now = datetime(2026, 4, 11, 12, 0, tzinfo=ET)
        info = get_session_info(now)
        assert "Weekend" in info.session_label


class TestTemporalResolution:
    def test_monday_reference(self) -> None:
        """'Monday' on a Friday should resolve to next Monday RTH."""
        now = datetime(2026, 4, 10, 18, 0, tzinfo=ET)
        result = resolve_temporal_reference("Is Monday going to be up?", now)
        assert result["horizon_minutes"] == 390
        assert "Monday" in str(result["session_label"])

    def test_today_during_rth(self) -> None:
        """'today' during RTH should resolve to remaining session."""
        now = datetime(2026, 4, 7, 14, 0, tzinfo=ET)
        result = resolve_temporal_reference("ES forecast for today", now)
        assert result["horizon_minutes"] == 120

    def test_today_after_close(self) -> None:
        """'today' after RTH close should resolve to full session."""
        now = datetime(2026, 4, 7, 18, 0, tzinfo=ET)
        result = resolve_temporal_reference("How was today?", now)
        assert result["horizon_minutes"] == 390

    def test_tomorrow_reference(self) -> None:
        """'tomorrow' should resolve to next business day RTH."""
        now = datetime(2026, 4, 10, 12, 0, tzinfo=ET)
        result = resolve_temporal_reference("tomorrow's forecast", now)
        assert result["horizon_minutes"] == 390
        assert "Monday" in str(result["session_label"])

    def test_end_of_day_during_rth(self) -> None:
        """'by close' during RTH should resolve to remaining."""
        now = datetime(2026, 4, 7, 15, 0, tzinfo=ET)
        result = resolve_temporal_reference("ES by close", now)
        assert result["horizon_minutes"] == 60

    def test_eod_outside_rth(self) -> None:
        """'by close' outside RTH should resolve to next session."""
        now = datetime(2026, 4, 7, 20, 0, tzinfo=ET)
        result = resolve_temporal_reference("ES by close", now)
        assert result["horizon_minutes"] == 390

    def test_no_temporal_reference(self) -> None:
        """Query without temporal reference should return None."""
        result = resolve_temporal_reference("Where will ES be?")
        assert result["horizon_minutes"] is None

    def test_this_week(self) -> None:
        """'this week' on Monday should cover ~5 days."""
        now = datetime(2026, 4, 6, 10, 0, tzinfo=ET)
        result = resolve_temporal_reference("ES this week forecast", now)
        assert result["horizon_minutes"] is not None
        assert result["horizon_minutes"] > 390

    def test_friday_reference(self) -> None:
        """'Friday' on a Monday should resolve to Friday."""
        now = datetime(2026, 4, 6, 10, 0, tzinfo=ET)
        result = resolve_temporal_reference("ES forecast for Friday", now)
        assert result["horizon_minutes"] == 390
        assert "Friday" in str(result["session_label"])

    def test_same_day_reference_during_rth(self) -> None:
        """'Tuesday' on Tuesday during RTH should resolve to remaining."""
        now = datetime(2026, 4, 7, 14, 0, tzinfo=ET)
        result = resolve_temporal_reference("Tuesday outlook", now)
        assert result["horizon_minutes"] is not None
        assert result["horizon_minutes"] < 390

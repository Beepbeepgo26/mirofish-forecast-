"""Test economic calendar client."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from mirofish_forecast.data.economic_calendar import EconomicCalendarClient
from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    EconomicEvent,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
)

ET = ZoneInfo("America/New_York")


class TestFOMCDetection:
    def test_detects_fomc_statement_day(self, mock_settings, mock_cache) -> None:
        """Should detect April 29, 2026 as an FOMC day."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        result = client._check_fomc(
            "2026-04-29",
            datetime(2026, 4, 29, 10, 0, tzinfo=ET),
        )
        assert result is not None
        assert result.name == "FOMC"
        assert result.impact == "critical"
        assert result.hours_until is not None
        assert result.hours_until > 0

    def test_detects_fomc_day1(self, mock_settings, mock_cache) -> None:
        """Should detect day 1 of a two-day FOMC meeting."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        result = client._check_fomc(
            "2026-04-28",
            datetime(2026, 4, 28, 10, 0, tzinfo=ET),
        )
        assert result is not None
        assert "Day 1" in result.full_name

    def test_non_fomc_day_returns_none(self, mock_settings, mock_cache) -> None:
        """Regular day should return None."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        result = client._check_fomc(
            "2026-04-15",
            datetime(2026, 4, 15, 10, 0, tzinfo=ET),
        )
        assert result is None

    def test_sep_meeting_flagged(self, mock_settings, mock_cache) -> None:
        """March 18 meeting should have SEP flag."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        result = client._check_fomc(
            "2026-03-18",
            datetime(2026, 3, 18, 10, 0, tzinfo=ET),
        )
        assert result is not None
        assert result.has_sep is True

    def test_all_fomc_dates_detected(self, mock_settings, mock_cache) -> None:
        """All 8 FOMC statement dates should be detected."""
        from mirofish_forecast.config.constants import FOMC_DATES_2026

        client = EconomicCalendarClient(mock_settings, mock_cache)
        for date_str in FOMC_DATES_2026:
            result = client._check_fomc(
                date_str,
                datetime.strptime(date_str, "%Y-%m-%d").replace(hour=10, tzinfo=ET),
            )
            assert result is not None, f"FOMC not detected on {date_str}"
            assert result.name == "FOMC"

    def test_fomc_hours_until_after_statement(self, mock_settings, mock_cache) -> None:
        """After 2 PM on FOMC day, hours_until should be negative."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        result = client._check_fomc(
            "2026-04-29",
            datetime(2026, 4, 29, 15, 0, tzinfo=ET),
        )
        assert result is not None
        assert result.hours_until < 0


class TestFREDReleases:
    @patch("mirofish_forecast.data.economic_calendar.requests.get")
    def test_detects_cpi_release(self, mock_get, mock_settings, mock_cache) -> None:
        """Should detect CPI release on matching day."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"release_dates": [{"date": "2026-04-14"}]}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = EconomicCalendarClient(mock_settings, mock_cache)
        events = client._check_fred_releases(
            "2026-04-14",
            datetime(2026, 4, 14, 7, 0, tzinfo=ET),
        )
        cpi_events = [e for e in events if e.name == "CPI"]
        assert len(cpi_events) >= 1
        assert cpi_events[0].impact == "high"
        assert cpi_events[0].hours_until > 0

    @patch("mirofish_forecast.data.economic_calendar.requests.get")
    def test_no_events_on_quiet_day(self, mock_get, mock_settings, mock_cache) -> None:
        """Should not crash on days with no releases."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"release_dates": []}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = EconomicCalendarClient(mock_settings, mock_cache)
        events = client._check_fred_releases(
            "2026-04-15",
            datetime(2026, 4, 15, 10, 0, tzinfo=ET),
        )
        assert isinstance(events, list)

    @patch("mirofish_forecast.data.economic_calendar.requests.get")
    def test_handles_fred_api_failure(self, mock_get, mock_settings, mock_cache) -> None:
        """FRED failure should not raise, just return empty list."""
        mock_get.side_effect = Exception("API down")

        client = EconomicCalendarClient(mock_settings, mock_cache)
        events = client._check_fred_releases(
            "2026-04-14",
            datetime(2026, 4, 14, 7, 0, tzinfo=ET),
        )
        assert isinstance(events, list)


class TestTimeParser:
    def test_parse_morning_time(self, mock_settings, mock_cache) -> None:
        """Should parse '08:30 ET' correctly."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        h, m = client._parse_time("08:30 ET")
        assert h == 8
        assert m == 30

    def test_parse_afternoon_time(self, mock_settings, mock_cache) -> None:
        """Should parse '14:00 ET' correctly."""
        client = EconomicCalendarClient(mock_settings, mock_cache)
        h, m = client._parse_time("14:00 ET")
        assert h == 14
        assert m == 0


class TestEventFormatting:
    def test_format_events_with_fomc(self, mock_settings) -> None:
        """Should format FOMC event with warning markers."""
        from mirofish_forecast.services.scenario_builder import (
            ScenarioBuilder,
        )

        ctx = MarketContext(
            macro=MacroIndicators(),
            vix=VIXData(),
            cross_asset=CrossAssetSnapshot(),
            fear_greed=FearGreedData(),
            internals=MarketInternals(),
            events_today=[
                EconomicEvent(
                    name="FOMC",
                    full_name="FOMC Rate Decision",
                    date="2026-04-29",
                    time="14:00 ET",
                    impact="critical",
                    hours_until=4.0,
                    has_press_conference=True,
                    has_sep=False,
                    is_today=True,
                ),
            ],
            assembled_at=datetime.utcnow(),
        )

        builder = ScenarioBuilder(mock_settings)
        text = builder._format_events_for_context(ctx)
        assert "FOMC" in text
        assert "CRITICAL" in text
        assert "BEFORE" in text

    def test_format_no_events(self, mock_settings) -> None:
        """Should return 'no events' text when empty."""
        from mirofish_forecast.services.scenario_builder import (
            ScenarioBuilder,
        )

        ctx = MarketContext(
            macro=MacroIndicators(),
            vix=VIXData(),
            cross_asset=CrossAssetSnapshot(),
            fear_greed=FearGreedData(),
            internals=MarketInternals(),
            assembled_at=datetime.utcnow(),
        )

        builder = ScenarioBuilder(mock_settings)
        text = builder._format_events_for_context(ctx)
        assert "No major" in text

    def test_format_imminent_event(self, mock_settings) -> None:
        """Events < 1 hour away should show IMMINENT."""
        from mirofish_forecast.services.scenario_builder import (
            ScenarioBuilder,
        )

        ctx = MarketContext(
            macro=MacroIndicators(),
            vix=VIXData(),
            cross_asset=CrossAssetSnapshot(),
            fear_greed=FearGreedData(),
            internals=MarketInternals(),
            events_today=[
                EconomicEvent(
                    name="CPI",
                    full_name="Consumer Price Index",
                    date="2026-04-14",
                    time="08:30 ET",
                    impact="high",
                    hours_until=0.5,
                    is_today=True,
                ),
            ],
            assembled_at=datetime.utcnow(),
        )

        builder = ScenarioBuilder(mock_settings)
        text = builder._format_events_for_context(ctx)
        assert "IMMINENT" in text


class TestEconomicEventModel:
    def test_event_model_creation(self) -> None:
        """Basic model creation should work."""
        event = EconomicEvent(
            name="CPI",
            full_name="Consumer Price Index",
            date="2026-04-14",
            time="08:30 ET",
            impact="high",
        )
        assert event.name == "CPI"
        assert event.impact == "high"
        assert event.is_today is False

    def test_event_serialization(self) -> None:
        """Should round-trip via JSON."""
        event = EconomicEvent(
            name="FOMC",
            full_name="FOMC Rate Decision",
            date="2026-04-29",
            time="14:00 ET",
            impact="critical",
            consensus="4.50%",
            prior="4.50%",
            has_sep=True,
        )
        data = event.model_dump()
        restored = EconomicEvent.model_validate(data)
        assert restored.name == "FOMC"
        assert restored.has_sep is True
        assert restored.consensus == "4.50%"

    def test_market_context_with_events(self) -> None:
        """MarketContext should accept events lists."""
        ctx = MarketContext(
            macro=MacroIndicators(),
            vix=VIXData(),
            cross_asset=CrossAssetSnapshot(),
            fear_greed=FearGreedData(),
            internals=MarketInternals(),
            events_today=[
                EconomicEvent(
                    name="NFP",
                    full_name="Nonfarm Payrolls",
                    date="2026-04-03",
                )
            ],
            assembled_at=datetime.utcnow(),
        )
        assert len(ctx.events_today) == 1
        assert ctx.events_today[0].name == "NFP"

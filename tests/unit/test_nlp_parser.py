"""Test the NLP parser — regex extraction and LLM fallback."""

from unittest.mock import patch

from mirofish_forecast.models.query import QueryType, SimPreset
from mirofish_forecast.services.nlp_parser import NLPParser


class TestRegexParsing:
    """Queries that should be handled by regex alone (no LLM call)."""

    def _parse(self, query, mock_settings):
        parser = NLPParser(mock_settings)
        return parser._try_regex_parse(query)

    def test_simple_es_horizon(self, mock_settings):
        result = self._parse("Where will ES be in 2 hours?", mock_settings)
        assert result is not None
        assert result.instrument == "ES"
        assert result.forecast_horizon_minutes == 120
        assert result.parse_method == "regex"

    def test_explicit_time_target(self, mock_settings):
        result = self._parse("ES price at 11:30 AM PT", mock_settings)
        assert result is not None
        assert result.target_time == "11:30 AM PT"

    def test_nq_with_minutes(self, mock_settings):
        result = self._parse("NQ next 30 minutes", mock_settings)
        assert result is not None
        assert result.instrument == "NQ"
        assert result.forecast_horizon_minutes == 30

    def test_price_target_extraction(self, mock_settings):
        result = self._parse("Will ES hit 5500 in 2 hours?", mock_settings)
        assert result is not None
        assert result.target_price == 5500.0
        assert result.query_type == QueryType.PROBABILITY_FORECAST

    def test_direction_bias_bullish(self, mock_settings):
        result = self._parse("Bullish on ES next 3 hours", mock_settings)
        assert result is not None
        assert result.direction_bias == "bullish"

    def test_direction_bias_bearish(self, mock_settings):
        result = self._parse("Bearish ES next 1 hour", mock_settings)
        assert result is not None
        assert result.direction_bias == "bearish"

    def test_default_instrument_is_es(self, mock_settings):
        result = self._parse("What's the range for the next 2 hours?", mock_settings)
        assert result is not None
        assert result.instrument == "ES"

    def test_returns_none_for_ambiguous_query(self, mock_settings):
        """Queries without time info should fall through to LLM."""
        result = self._parse("What happens if the Fed pauses?", mock_settings)
        assert result is None

    def test_returns_none_for_event_query(self, mock_settings):
        result = self._parse("How will FOMC affect S&P futures?", mock_settings)
        assert result is None

    def test_day_horizon(self, mock_settings):
        result = self._parse("ES forecast for 3 days", mock_settings)
        assert result is not None
        assert result.forecast_horizon_minutes == 3 * 24 * 60


class TestSimPresets:
    """Test simulation preset resolution."""

    def test_quick_preset(self, mock_settings):
        parser = NLPParser(mock_settings)
        preset, count = parser._resolve_sim_config("quick", None)
        assert preset == SimPreset.QUICK
        assert count == 100

    def test_standard_preset(self, mock_settings):
        parser = NLPParser(mock_settings)
        preset, count = parser._resolve_sim_config("standard", None)
        assert preset == SimPreset.STANDARD
        assert count == 200

    def test_deep_preset(self, mock_settings):
        parser = NLPParser(mock_settings)
        preset, count = parser._resolve_sim_config("deep", None)
        assert preset == SimPreset.DEEP
        assert count == 500

    def test_custom_count_overrides_preset(self, mock_settings):
        parser = NLPParser(mock_settings)
        preset, count = parser._resolve_sim_config("standard", 350)
        assert preset == SimPreset.CUSTOM
        assert count == 350

    def test_custom_count_clamped_low(self, mock_settings):
        parser = NLPParser(mock_settings)
        _, count = parser._resolve_sim_config("standard", 50)
        assert count == 100

    def test_custom_count_clamped_high(self, mock_settings):
        parser = NLPParser(mock_settings)
        _, count = parser._resolve_sim_config("standard", 999)
        assert count == 500


class TestLLMFallback:
    """Test the LLM parsing path."""

    @patch("mirofish_forecast.services.nlp_parser.LLMClient")
    def test_llm_parse_on_ambiguous_query(self, mock_llm_cls, mock_settings):
        from mirofish_forecast.llm.schemas import ParsedForecastQuery, ParsedQueryType

        mock_parsed = ParsedForecastQuery(
            instrument="ES",
            query_type=ParsedQueryType.scenario_forecast,
            target_time=None,
            forecast_horizon_minutes=180,
            target_price=None,
            direction_bias=None,
            additional_context="FOMC announcement expected",
            mentions_event="FOMC",
        )
        mock_llm_cls.return_value.parse_structured.return_value = mock_parsed

        parser = NLPParser(mock_settings)
        result = parser.parse("What happens to ES if the Fed pauses rates?")

        assert result.instrument == "ES"
        assert result.query_type == QueryType.SCENARIO_FORECAST
        assert result.mentions_event == "FOMC"
        assert result.parse_method == "llm"

    @patch("mirofish_forecast.services.nlp_parser.LLMClient")
    def test_llm_failure_returns_fallback(self, mock_llm_cls, mock_settings):
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("API error")

        parser = NLPParser(mock_settings)
        result = parser.parse("Something completely unparseable without time")

        # Should not crash — returns defaults
        assert result.instrument == "ES"
        assert result.parse_method == "fallback"

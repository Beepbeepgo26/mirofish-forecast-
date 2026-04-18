"""Test the scenario builder service."""

from datetime import datetime
from unittest.mock import patch

from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
    VIXRegime,
)
from mirofish_forecast.models.query import ForecastQuery, QueryType
from mirofish_forecast.models.scenario import MarketRegime, ScenarioRank
from mirofish_forecast.services.scenario_builder import ScenarioBuilder


def _make_context(**overrides):
    """Build a test MarketContext with sensible defaults."""
    defaults = {
        "macro": MacroIndicators(
            fed_funds_rate=5.25,
            ten_year_yield=4.35,
            two_year_yield=3.82,
            ten_year_2_year_spread=0.53,
            cpi_yoy=2.8,
            gdp_growth=2.4,
            unemployment_rate=4.0,
            vix_close=22.3,
        ),
        "vix": VIXData(spot=22.3, regime=VIXRegime.ELEVATED),
        "cross_asset": CrossAssetSnapshot(
            es_price=5420.0,
            nq_price=18900.0,
            spy_price=540.0,
            dxy_price=104.2,
            tlt_price=87.5,
            gld_price=2350.0,
            crude_price=78.5,
        ),
        "fear_greed": FearGreedData(value=38.0, description="Fear"),
        "internals": MarketInternals(nyse_tick=-200.0, nyse_add=-500.0, nyse_vold=-1200.0),
        "assembled_at": datetime.utcnow(),
    }
    defaults.update(overrides)
    return MarketContext(**defaults)


def _make_query(**overrides):
    """Build a test ForecastQuery with sensible defaults."""
    defaults = {
        "raw_query": "Where will ES be in 2 hours?",
        "instrument": "ES",
        "query_type": QueryType.RANGE_FORECAST,
        "forecast_horizon_minutes": 120,
        "parsed_at": datetime.utcnow(),
        "parse_method": "regex",
    }
    defaults.update(overrides)
    return ForecastQuery(**defaults)


class TestScenarioBuilderTemplate:
    """Test the template fallback path (no LLM calls)."""

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_template_fallback_produces_valid_scenario(self, mock_llm_cls, mock_settings):
        """If LLM fails, template should still produce a valid SimulationScenario."""
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context()
        query = _make_query()

        scenario = builder.build(query, context)

        assert scenario.instrument == "ES"
        assert scenario.current_price == 5420.0
        assert len(scenario.scenarios) == 3
        assert scenario.build_method == "template"

        # Probabilities sum to 1.0
        total = sum(s.probability for s in scenario.scenarios)
        assert abs(total - 1.0) < 0.01

        # All three ranks present
        ranks = {s.rank for s in scenario.scenarios}
        assert ScenarioRank.MOST_PROBABLE in ranks
        assert ScenarioRank.SECONDARY in ranks
        assert ScenarioRank.FAILURE_TRAP in ranks

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_high_vix_fear_produces_volatile_regime(self, mock_llm_cls, mock_settings):
        """High VIX + low Fear & Greed should produce volatile/breakdown regime."""
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context(
            vix=VIXData(spot=32.0, regime=VIXRegime.FEAR),
            fear_greed=FearGreedData(value=15.0, description="Extreme Fear"),
        )
        query = _make_query()
        scenario = builder.build(query, context)

        assert scenario.market_regime in (
            MarketRegime.BREAKDOWN,
            MarketRegime.VOLATILE_CHOP,
        )

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_low_vix_greed_produces_range(self, mock_llm_cls, mock_settings):
        """Low VIX + high Fear & Greed should produce tight range or trending up."""
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context(
            vix=VIXData(spot=12.0, regime=VIXRegime.COMPLACENT),
            fear_greed=FearGreedData(value=75.0, description="Greed"),
        )
        query = _make_query()
        scenario = builder.build(query, context)

        assert scenario.market_regime in (
            MarketRegime.TIGHT_RANGE,
            MarketRegime.TRENDING_UP,
        )


class TestContextBlockTemplates:
    """Test the deterministic context block templates."""

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_institutional_context_contains_macro(self, mock_llm_cls, mock_settings):
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context()
        query = _make_query()
        scenario = builder.build(query, context)

        text = scenario.institutional_context.context_text
        assert "MACRO" in text
        assert "Fed Funds" in text or "5.25" in text

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_retail_context_contains_sentiment(self, mock_llm_cls, mock_settings):
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context()
        query = _make_query()
        scenario = builder.build(query, context)

        text = scenario.retail_context.context_text
        assert "SENTIMENT" in text or "Fear" in text

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_market_maker_context_contains_flow(self, mock_llm_cls, mock_settings):
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context()
        query = _make_query()
        scenario = builder.build(query, context)

        text = scenario.market_maker_context.context_text
        assert "FLOW" in text or "TICK" in text

    @patch("mirofish_forecast.services.scenario_builder.LLMClient")
    def test_context_handles_missing_ib_data(self, mock_llm_cls, mock_settings):
        """Market maker context should gracefully handle null IB internals."""
        mock_llm_cls.return_value.parse_structured.side_effect = Exception("LLM unavailable")

        builder = ScenarioBuilder(mock_settings)
        context = _make_context(internals=MarketInternals())
        query = _make_query()
        scenario = builder.build(query, context)

        text = scenario.market_maker_context.context_text
        # New template shows "N/A" for TICK/ADD/VOLD and "offline" in the footnote
        assert "N/A" in text or "offline" in text  # Should indicate IB relay not configured

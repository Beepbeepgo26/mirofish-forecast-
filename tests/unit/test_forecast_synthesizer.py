"""Test forecast synthesizer."""

import time
from datetime import datetime
from unittest.mock import patch

from mirofish_forecast.models.forecast import AgentDecision, SimulationResult
from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
    VIXRegime,
)
from mirofish_forecast.models.scenario import (
    AgentContextBlock,
    MarketRegime,
    ScenarioOutcome,
    ScenarioRank,
    SimulationScenario,
)
from mirofish_forecast.services.forecast_synthesizer import ForecastSynthesizer


def _make_sim_results(n: int = 10, base_price: float = 5420.0) -> list[SimulationResult]:
    results = []
    for i in range(n):
        results.append(
            SimulationResult(
                sim_id=i,
                seed=i,
                temperature=0.7,
                final_price=base_price + (i - n / 2) * 2,
                agent_decisions=[
                    AgentDecision(
                        agent_type="institutional",
                        direction="long",
                        confidence=0.65,
                        price_target=base_price + 10,
                        reasoning="Bullish macro",
                    ),
                    AgentDecision(
                        agent_type="retail",
                        direction="long",
                        confidence=0.55,
                        price_target=base_price + 5,
                        reasoning="Sentiment positive",
                    ),
                    AgentDecision(
                        agent_type="market_maker",
                        direction="neutral",
                        confidence=0.50,
                        price_target=base_price,
                        reasoning="Balanced flow",
                    ),
                ],
                success=True,
            )
        )
    return results


def _make_scenario() -> SimulationScenario:
    return SimulationScenario(
        instrument="ES",
        forecast_horizon_minutes=120,
        current_price=5420.0,
        market_regime=MarketRegime.TIGHT_RANGE,
        scenarios=[
            ScenarioOutcome(
                rank=ScenarioRank.MOST_PROBABLE,
                name="Range",
                description="Range",
                probability=0.55,
                price_range_low=5400,
                price_range_high=5440,
            ),
            ScenarioOutcome(
                rank=ScenarioRank.SECONDARY,
                name="Up",
                description="Up",
                probability=0.30,
                price_range_low=5440,
                price_range_high=5460,
            ),
            ScenarioOutcome(
                rank=ScenarioRank.FAILURE_TRAP,
                name="Down",
                description="Down",
                probability=0.15,
                price_range_low=5380,
                price_range_high=5400,
            ),
        ],
        institutional_context=AgentContextBlock(agent_type="institutional", context_text="test"),
        retail_context=AgentContextBlock(agent_type="retail", context_text="test"),
        market_maker_context=AgentContextBlock(agent_type="market_maker", context_text="test"),
        built_at=datetime.utcnow(),
    )


def _make_context() -> MarketContext:
    return MarketContext(
        macro=MacroIndicators(fed_funds_rate=5.25, ten_year_yield=4.35),
        vix=VIXData(spot=22.3, regime=VIXRegime.ELEVATED),
        cross_asset=CrossAssetSnapshot(es_price=5420.0, dxy_price=104.2),
        fear_greed=FearGreedData(value=38.0, description="Fear"),
        internals=MarketInternals(),
        assembled_at=datetime.utcnow(),
    )


class TestForecastSynthesizer:
    @patch("mirofish_forecast.services.forecast_synthesizer.LLMClient")
    def test_produces_forecast(self, mock_llm_cls, mock_settings):
        mock_llm_cls.return_value.chat.return_value = (
            "ES is likely to trade between 5405-5435 over the next 2 hours."
        )

        synth = ForecastSynthesizer(mock_settings)
        forecast = synth.synthesize(
            results=_make_sim_results(),
            scenario=_make_scenario(),
            context=_make_context(),
            forecast_id="test123",
            sim_preset="standard",
            pipeline_start_time=time.time() - 60,
        )

        assert forecast.forecast_id == "test123"
        assert forecast.forecast_text != ""
        assert forecast.distribution.median > 0
        assert forecast.successful_simulations == 10

    @patch("mirofish_forecast.services.forecast_synthesizer.LLMClient")
    def test_handles_low_success_rate(self, mock_llm_cls, mock_settings):
        """Should return error forecast if too many sims fail."""
        results = _make_sim_results(n=10)
        # Mark 5 as failed (50% < 70% threshold)
        for i in range(5):
            results[i] = results[i].model_copy(update={"success": False})

        synth = ForecastSynthesizer(mock_settings)
        forecast = synth.synthesize(
            results=results,
            scenario=_make_scenario(),
            context=_make_context(),
            forecast_id="test_fail",
            sim_preset="standard",
            pipeline_start_time=time.time(),
        )

        assert "could not be generated" in forecast.forecast_text.lower()
        assert forecast.build_method == "error"

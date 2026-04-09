"""Test the forecast pipeline."""

from datetime import datetime
from queue import Queue
from unittest.mock import patch

from mirofish_forecast.config import constants
from mirofish_forecast.models.forecast import (
    AgentDecision,
    ForecastResult,
    ProbabilityDistribution,
    SimulationResult,
)
from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
)
from mirofish_forecast.models.query import ForecastQuery, QueryType
from mirofish_forecast.models.scenario import (
    AgentContextBlock,
    MarketRegime,
    ScenarioOutcome,
    ScenarioRank,
    SimulationScenario,
)
from mirofish_forecast.services.pipeline import ForecastPipeline


class TestForecastPipeline:
    def _make_mock_context(self):
        return MarketContext(
            macro=MacroIndicators(fed_funds_rate=5.25),
            vix=VIXData(spot=22.3),
            cross_asset=CrossAssetSnapshot(es_price=5420.0),
            fear_greed=FearGreedData(value=38.0, description="Fear"),
            internals=MarketInternals(),
            assembled_at=datetime.utcnow(),
        )

    def _make_mock_query(self):
        return ForecastQuery(
            raw_query="Where will ES be in 2 hours?",
            instrument="ES",
            query_type=QueryType.RANGE_FORECAST,
            forecast_horizon_minutes=120,
            parsed_at=datetime.utcnow(),
            parse_method="regex",
        )

    def _make_mock_scenario(self):
        return SimulationScenario(
            instrument="ES",
            forecast_horizon_minutes=120,
            current_price=5420.0,
            market_regime=MarketRegime.TIGHT_RANGE,
            scenarios=[
                ScenarioOutcome(
                    rank=ScenarioRank.MOST_PROBABLE,
                    name="Range",
                    description="Test",
                    probability=0.55,
                ),
                ScenarioOutcome(
                    rank=ScenarioRank.SECONDARY,
                    name="Breakout",
                    description="Test",
                    probability=0.30,
                ),
                ScenarioOutcome(
                    rank=ScenarioRank.FAILURE_TRAP,
                    name="Trap",
                    description="Test",
                    probability=0.15,
                ),
            ],
            institutional_context=AgentContextBlock(
                agent_type="institutional", context_text="test"
            ),
            retail_context=AgentContextBlock(agent_type="retail", context_text="test"),
            market_maker_context=AgentContextBlock(agent_type="market_maker", context_text="test"),
            built_at=datetime.utcnow(),
        )

    def _make_mock_sim_results(self):
        return [
            SimulationResult(
                sim_id=i,
                seed=i,
                temperature=0.7,
                final_price=5420.0 + i,
                agent_decisions=[
                    AgentDecision(
                        agent_type="institutional",
                        direction="long",
                        confidence=0.6,
                        reasoning="Test",
                    ),
                ],
                success=True,
            )
            for i in range(10)
        ]

    def _make_mock_forecast(self):
        return ForecastResult(
            forecast_id="test",
            instrument="ES",
            forecast_horizon_minutes=120,
            current_price=5420.0,
            forecast_text="ES is likely to trade in a range.",
            distribution=ProbabilityDistribution(
                median=5425.0,
                mean=5424.5,
                std_dev=5.0,
                percentile_5=5415.0,
                percentile_25=5420.0,
                percentile_75=5428.0,
                percentile_95=5432.0,
                skewness=0.1,
                prob_up=0.55,
                prob_down=0.30,
                prob_flat=0.15,
            ),
            total_simulations=10,
            successful_simulations=10,
            sim_preset="standard",
            created_at=datetime.utcnow(),
            pipeline_duration_seconds=5.0,
        )

    @patch("mirofish_forecast.services.pipeline.ForecastSynthesizer")
    @patch("mirofish_forecast.services.pipeline.MonteCarloRunner")
    @patch("mirofish_forecast.services.pipeline.ScenarioBuilder")
    @patch("mirofish_forecast.services.pipeline.DataAggregator")
    @patch("mirofish_forecast.services.pipeline.NLPParser")
    def test_pipeline_emits_all_stages(
        self,
        mock_parser,
        mock_aggregator,
        mock_scenario_builder,
        mock_runner,
        mock_synthesizer,
        mock_settings,
    ):
        mock_parser.return_value.parse.return_value = self._make_mock_query()
        mock_aggregator.return_value.get_market_context.return_value = self._make_mock_context()
        mock_scenario_builder.return_value.build.return_value = self._make_mock_scenario()
        mock_runner.return_value.run.return_value = self._make_mock_sim_results()
        mock_synthesizer.return_value.synthesize.return_value = self._make_mock_forecast()

        queue = Queue()
        pipeline = ForecastPipeline(mock_settings, queue)
        pipeline.run("Where will ES be in 2 hours?", forecast_id="test")

        events = []
        while not queue.empty():
            events.append(queue.get())

        stages = [e["stage"] for e in events]

        # All 5 stages + complete
        assert constants.STAGE_PARSING in stages
        assert constants.STAGE_DATA_COLLECTION in stages
        assert constants.STAGE_SCENARIO_BUILDING in stages
        assert constants.STAGE_SIMULATION in stages
        assert constants.STAGE_SYNTHESIS in stages
        assert constants.STAGE_COMPLETE in stages

    @patch("mirofish_forecast.services.pipeline.ForecastSynthesizer")
    @patch("mirofish_forecast.services.pipeline.MonteCarloRunner")
    @patch("mirofish_forecast.services.pipeline.ScenarioBuilder")
    @patch("mirofish_forecast.services.pipeline.DataAggregator")
    @patch("mirofish_forecast.services.pipeline.NLPParser")
    def test_pipeline_emits_error_on_failure(
        self,
        mock_parser,
        mock_aggregator,
        mock_scenario_builder,
        mock_runner,
        mock_synthesizer,
        mock_settings,
    ):
        mock_parser.return_value.parse.side_effect = Exception("Parse failed")

        queue = Queue()
        pipeline = ForecastPipeline(mock_settings, queue)
        pipeline.run("bad query", forecast_id="test")

        events = []
        while not queue.empty():
            events.append(queue.get())

        stages = [e["stage"] for e in events]
        assert constants.STAGE_ERROR in stages

    @patch("mirofish_forecast.services.pipeline.ForecastSynthesizer")
    @patch("mirofish_forecast.services.pipeline.MonteCarloRunner")
    @patch("mirofish_forecast.services.pipeline.ScenarioBuilder")
    @patch("mirofish_forecast.services.pipeline.DataAggregator")
    @patch("mirofish_forecast.services.pipeline.NLPParser")
    def test_complete_event_contains_forecast(
        self,
        mock_parser,
        mock_aggregator,
        mock_scenario_builder,
        mock_runner,
        mock_synthesizer,
        mock_settings,
    ):
        mock_parser.return_value.parse.return_value = self._make_mock_query()
        mock_aggregator.return_value.get_market_context.return_value = self._make_mock_context()
        mock_scenario_builder.return_value.build.return_value = self._make_mock_scenario()
        mock_runner.return_value.run.return_value = self._make_mock_sim_results()
        mock_synthesizer.return_value.synthesize.return_value = self._make_mock_forecast()

        queue = Queue()
        pipeline = ForecastPipeline(mock_settings, queue)
        pipeline.run("Where will ES be in 2 hours?", forecast_id="test")

        events = []
        while not queue.empty():
            events.append(queue.get())

        complete_event = [e for e in events if e["stage"] == constants.STAGE_COMPLETE][0]
        assert "forecast" in complete_event
        assert complete_event["forecast"]["instrument"] == "ES"
        assert "forecast_text" in complete_event["forecast"]

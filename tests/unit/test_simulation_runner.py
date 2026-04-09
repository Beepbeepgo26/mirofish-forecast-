"""Test Monte Carlo runner — uses mocked LLM responses."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from mirofish_forecast.models.scenario import (
    AgentContextBlock,
    MarketRegime,
    ScenarioOutcome,
    ScenarioRank,
    SimulationScenario,
)
from mirofish_forecast.services.simulation_runner import MonteCarloRunner


def _make_scenario() -> SimulationScenario:
    return SimulationScenario(
        instrument="ES",
        forecast_horizon_minutes=120,
        current_price=5420.0,
        market_regime=MarketRegime.TIGHT_RANGE,
        key_levels=[],
        scenarios=[
            ScenarioOutcome(
                rank=ScenarioRank.MOST_PROBABLE,
                name="Range",
                description="Tight range",
                probability=0.55,
            ),
            ScenarioOutcome(
                rank=ScenarioRank.SECONDARY,
                name="Up",
                description="Move higher",
                probability=0.30,
            ),
            ScenarioOutcome(
                rank=ScenarioRank.FAILURE_TRAP,
                name="Down",
                description="Selloff",
                probability=0.15,
            ),
        ],
        institutional_context=AgentContextBlock(
            agent_type="institutional", context_text="Test macro context"
        ),
        retail_context=AgentContextBlock(
            agent_type="retail", context_text="Test sentiment context"
        ),
        market_maker_context=AgentContextBlock(
            agent_type="market_maker", context_text="Test flow context"
        ),
        built_at=datetime.utcnow(),
    )


class TestMonteCarloRunner:
    @patch("mirofish_forecast.services.simulation_runner.AsyncOpenAI")
    def test_produces_results(self, mock_async_openai, mock_settings):
        """Runner should produce N simulation results."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "direction": "long",
                "confidence": 0.65,
                "price_target": 5425.0,
                "reasoning": "Bullish momentum.",
            }
        )

        mock_client = mock_async_openai.return_value
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        runner = MonteCarloRunner(mock_settings)
        results = runner.run(_make_scenario(), sim_count=5)

        assert len(results) == 5
        assert all(r.sim_id >= 0 for r in results)

    @patch("mirofish_forecast.services.simulation_runner.AsyncOpenAI")
    def test_handles_llm_failures(self, mock_async_openai, mock_settings):
        """Runner should gracefully handle LLM failures."""
        mock_client = mock_async_openai.return_value
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API Error"))

        runner = MonteCarloRunner(mock_settings)
        results = runner.run(_make_scenario(), sim_count=3)

        # Should still produce results (with fallback agent decisions)
        assert len(results) == 3
        # Simulations should still succeed (agent failures are handled per-agent)
        assert all(r.success for r in results)

    @patch("mirofish_forecast.services.simulation_runner.AsyncOpenAI")
    def test_progress_callback(self, mock_async_openai, mock_settings):
        """Progress callback should fire for each completed simulation."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "direction": "neutral",
                "confidence": 0.5,
                "price_target": 5420.0,
                "reasoning": "Flat.",
            }
        )
        mock_client = mock_async_openai.return_value
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        progress_calls: list[tuple[int, int]] = []

        def on_progress(completed: int, total: int) -> None:
            progress_calls.append((completed, total))

        runner = MonteCarloRunner(mock_settings)
        runner.run(_make_scenario(), sim_count=5, progress_callback=on_progress)

        assert len(progress_calls) == 5
        assert progress_calls[-1] == (5, 5)

    @patch("mirofish_forecast.services.simulation_runner.AsyncOpenAI")
    def test_price_stays_near_start(self, mock_async_openai, mock_settings):
        """Final prices should stay within a realistic range of the starting price."""
        # Agent always returns a target 50 points above current — should get clamped
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "direction": "long",
                "confidence": 0.9,
                "price_target": 5470.0,  # 50 pts above start of 5420
                "reasoning": "Very bullish.",
            }
        )
        mock_client = mock_async_openai.return_value
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        runner = MonteCarloRunner(mock_settings)
        results = runner.run(_make_scenario(), sim_count=3)

        for r in results:
            if r.success:
                # Price should not drift more than ~2% from starting price (5420)
                drift_pct = abs(r.final_price - 5420.0) / 5420.0
                assert drift_pct < 0.02, (
                    f"Price drifted {drift_pct:.1%} to {r.final_price} — clamp is not working"
                )

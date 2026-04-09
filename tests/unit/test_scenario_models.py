"""Test scenario Pydantic models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from mirofish_forecast.models.scenario import (
    AgentContextBlock,
    KeyLevel,
    MarketRegime,
    ScenarioOutcome,
    ScenarioRank,
    SimulationScenario,
)


class TestScenarioOutcome:
    def test_valid_creation(self):
        s = ScenarioOutcome(
            rank=ScenarioRank.MOST_PROBABLE,
            name="Range-bound near 5420",
            description="ES consolidates around current levels.",
            probability=0.55,
            price_target=5420.0,
        )
        assert s.probability == 0.55

    def test_frozen(self):
        s = ScenarioOutcome(
            rank=ScenarioRank.MOST_PROBABLE,
            name="Test",
            description="Test",
            probability=0.5,
        )
        with pytest.raises(ValidationError):
            s.probability = 0.6

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            ScenarioOutcome(
                rank=ScenarioRank.MOST_PROBABLE,
                name="Test",
                description="Test",
                probability=0.5,
                bogus=True,
            )


class TestSimulationScenario:
    def test_full_assembly(self):
        scenario = SimulationScenario(
            instrument="ES",
            forecast_horizon_minutes=120,
            current_price=5420.0,
            market_regime=MarketRegime.TIGHT_RANGE,
            always_in_direction="long",
            market_state_score=6.5,
            key_levels=[
                KeyLevel(
                    price=5400.0,
                    label="Support",
                    significance="high",
                    source="Round number",
                ),
            ],
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
                agent_type="institutional",
                context_text="=== MACRO ===\nTest",
                priority_signals=["VIX elevated"],
            ),
            retail_context=AgentContextBlock(
                agent_type="retail",
                context_text="=== SENTIMENT ===\nTest",
                priority_signals=["Fear & Greed: 38"],
            ),
            market_maker_context=AgentContextBlock(
                agent_type="market_maker",
                context_text="=== FLOW ===\nTest",
                priority_signals=["TICK negative"],
            ),
            built_at=datetime.utcnow(),
        )
        assert len(scenario.scenarios) == 3
        assert sum(s.probability for s in scenario.scenarios) == 1.0
        assert scenario.market_regime == MarketRegime.TIGHT_RANGE

    def test_serialization_roundtrip(self):
        scenario = SimulationScenario(
            instrument="ES",
            forecast_horizon_minutes=120,
            market_regime=MarketRegime.VOLATILE_CHOP,
            key_levels=[],
            scenarios=[
                ScenarioOutcome(
                    rank=ScenarioRank.MOST_PROBABLE,
                    name="A",
                    description="A",
                    probability=0.5,
                ),
                ScenarioOutcome(
                    rank=ScenarioRank.SECONDARY,
                    name="B",
                    description="B",
                    probability=0.3,
                ),
                ScenarioOutcome(
                    rank=ScenarioRank.FAILURE_TRAP,
                    name="C",
                    description="C",
                    probability=0.2,
                ),
            ],
            institutional_context=AgentContextBlock(
                agent_type="institutional", context_text="test"
            ),
            retail_context=AgentContextBlock(agent_type="retail", context_text="test"),
            market_maker_context=AgentContextBlock(agent_type="market_maker", context_text="test"),
            built_at=datetime.utcnow(),
        )
        json_str = scenario.model_dump_json()
        restored = SimulationScenario.model_validate_json(json_str)
        assert restored.instrument == "ES"
        assert len(restored.scenarios) == 3

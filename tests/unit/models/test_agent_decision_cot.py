"""Tests for CoT reasoning persistence on AgentDecision."""

import json

from mirofish_forecast.models.forecast import AgentDecision


class TestAgentDecisionCotReasoning:
    """Verify cot_reasoning field on AgentDecision."""

    def test_accepts_cot_reasoning(self) -> None:
        """AgentDecision accepts cot_reasoning as optional string."""
        decision = AgentDecision(
            agent_type="institutional",
            direction="long",
            confidence=0.75,
            reasoning="short summary",
            cot_reasoning="Step 1: Analyzed trend...\nStep 2: Checked analogs...",
        )
        assert decision.cot_reasoning == "Step 1: Analyzed trend...\nStep 2: Checked analogs..."

    def test_cot_reasoning_default_none(self) -> None:
        """AgentDecision with cot_reasoning=None (historical data) works."""
        decision = AgentDecision(
            agent_type="retail",
            direction="short",
            confidence=0.6,
        )
        assert decision.cot_reasoning is None

    def test_json_round_trip_with_cot(self) -> None:
        """AgentDecision round-trips through JSON with cot_reasoning preserved."""
        original = AgentDecision(
            agent_type="market_maker",
            direction="neutral",
            confidence=0.55,
            reasoning="short extract",
            cot_reasoning="Full 8-step reasoning with analog references",
            signal_bar_score=72,
            regime="TREND",
        )
        serialized = original.model_dump_json()
        parsed = json.loads(serialized)

        assert parsed["cot_reasoning"] == "Full 8-step reasoning with analog references"

        restored = AgentDecision.model_validate_json(serialized)
        assert restored.cot_reasoning == original.cot_reasoning
        assert restored.reasoning == original.reasoning
        assert restored.agent_type == original.agent_type

    def test_json_round_trip_without_cot(self) -> None:
        """AgentDecision without cot_reasoning serializes correctly."""
        original = AgentDecision(
            agent_type="institutional",
            direction="long",
            confidence=0.8,
        )
        serialized = original.model_dump_json()
        parsed = json.loads(serialized)

        assert parsed["cot_reasoning"] is None

        restored = AgentDecision.model_validate_json(serialized)
        assert restored.cot_reasoning is None

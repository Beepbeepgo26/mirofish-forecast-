"""Simulation scenario models — output of the scenario builder, input to the Monte Carlo runner."""

from datetime import datetime
from enum import StrEnum

from mirofish_forecast.models.base import MiroFishBaseModel


class ScenarioRank(StrEnum):
    """Ranking of scenario likelihood."""

    MOST_PROBABLE = "most_probable"
    SECONDARY = "secondary"
    FAILURE_TRAP = "failure_trap"


class MarketRegime(StrEnum):
    """Current market regime classification."""

    TIGHT_RANGE = "tight_range"
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"
    VOLATILE_CHOP = "volatile_chop"
    TREND_DAY_UP = "trend_day_up"
    TREND_DAY_DOWN = "trend_day_down"


class KeyLevel(MiroFishBaseModel):
    """A significant price level with context."""

    price: float
    label: str  # "Support", "Resistance", "Gamma Flip", etc.
    significance: str = "medium"  # "low", "medium", "high"
    source: str | None = None  # "Al Brooks", "GEX", "round number", etc.


class ScenarioOutcome(MiroFishBaseModel):
    """One of three ranked scenarios for the forecast period."""

    rank: ScenarioRank
    name: str  # "Continued Range", "Breakout to 5450", etc.
    description: str  # 1-2 sentence narrative
    probability: float  # 0.0 to 1.0
    price_target: float | None = None  # Expected price if scenario plays out
    price_range_low: float | None = None  # Expected low bound
    price_range_high: float | None = None  # Expected high bound
    trigger: str | None = None  # What activates this scenario
    invalidation: str | None = None  # What kills this scenario
    key_risk: str | None = None  # Primary risk factor


class AgentContextBlock(MiroFishBaseModel):
    """Pre-formatted context block for a specific agent type.

    This is the interpretive text that gets injected into the agent's prompt,
    NOT the raw data. The scenario builder uses an LLM call to translate
    raw MarketContext numbers into agent-appropriate narrative.
    """

    agent_type: str  # "institutional", "retail", "market_maker"
    context_text: str  # The formatted context block for the prompt
    priority_signals: list[str] = []  # Top 3 signals this agent should focus on


class SimulationScenario(MiroFishBaseModel):
    """Complete scenario specification for the Monte Carlo runner.

    This is the output of the scenario builder and the primary input to Phase 4.
    Contains everything needed to run N simulations with different seeds.
    """

    # What we're forecasting
    instrument: str
    forecast_horizon_minutes: int
    current_price: float | None = None
    target_time: str | None = None

    # Market state
    market_regime: MarketRegime
    always_in_direction: str | None = None  # "long", "short", "neutral"
    market_state_score: float | None = None  # 0-10 from Al Brooks analysis

    # Key levels
    key_levels: list[KeyLevel] = []

    # Three ranked scenarios
    scenarios: list[ScenarioOutcome] = []  # Exactly 3: most_probable, secondary, failure_trap

    # Agent-specific context blocks
    institutional_context: AgentContextBlock
    retail_context: AgentContextBlock
    market_maker_context: AgentContextBlock

    # Metadata
    built_at: datetime
    build_method: str = "llm"  # "llm" or "template"

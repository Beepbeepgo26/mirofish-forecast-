"""OpenAI-compatible Pydantic schemas for structured output.

These are intentionally simpler than the domain models in models/query.py.
OpenAI's JSON Schema parser rejects many Pydantic v2 features.
"""

from enum import StrEnum

from pydantic import BaseModel


class ParsedQueryType(StrEnum):
    point_forecast = "point_forecast"
    range_forecast = "range_forecast"
    probability_forecast = "probability_forecast"
    direction_forecast = "direction_forecast"
    scenario_forecast = "scenario_forecast"


class ParsedForecastQuery(BaseModel):
    """Schema sent to GPT-4o for structured output parsing.

    Keep this flat and simple — no nested models, no Optional with complex defaults,
    no regex validators. GPT-4o strict mode requires strict JSON Schema compliance.
    """

    instrument: str
    query_type: ParsedQueryType
    target_time: str | None = None
    forecast_horizon_minutes: int
    target_price: float | None = None
    direction_bias: str | None = None
    additional_context: str | None = None
    mentions_event: str | None = None


# --- Scenario Generation Schemas (Phase 3) ---


class ParsedKeyLevel(BaseModel):
    """A key price level identified by the scenario builder."""

    price: float
    label: str
    significance: str
    source: str


class ParsedScenarioOutcome(BaseModel):
    """One of three ranked scenarios."""

    rank: str  # "most_probable", "secondary", "failure_trap"
    name: str
    description: str
    probability: float
    price_target: float | None = None
    price_range_low: float | None = None
    price_range_high: float | None = None
    trigger: str | None = None
    invalidation: str | None = None
    key_risk: str | None = None


class ParsedScenarioSet(BaseModel):
    """Complete scenario output from the LLM."""

    market_regime: str
    always_in_direction: str
    market_state_score: float
    key_levels: list[ParsedKeyLevel]
    scenarios: list[ParsedScenarioOutcome]


class ParsedAgentContext(BaseModel):
    """Context block for one agent type."""

    context: str
    priority_signals: list[str]


class ParsedContextBlocks(BaseModel):
    """All three agent context blocks from the interpreter."""

    institutional: ParsedAgentContext
    retail: ParsedAgentContext
    market_maker: ParsedAgentContext

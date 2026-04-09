"""Forecast query models — output of the NLP parser."""

from datetime import datetime
from enum import StrEnum

from mirofish_forecast.models.base import MiroFishBaseModel


class QueryType(StrEnum):
    """Type of forecast the user is requesting."""

    POINT_FORECAST = "point_forecast"  # "Where will ES be at 11:30?"
    RANGE_FORECAST = "range_forecast"  # "What's the likely range for ES today?"
    PROBABILITY_FORECAST = "probability_forecast"  # "What's the probability ES hits 5500?"
    DIRECTION_FORECAST = "direction_forecast"  # "Is ES going up or down?"
    SCENARIO_FORECAST = "scenario_forecast"  # "What are the scenarios for ES?"


class SimPreset(StrEnum):
    """Simulation tier presets."""

    QUICK = "quick"  # 100 sims
    STANDARD = "standard"  # 200 sims
    DEEP = "deep"  # 500 sims
    CUSTOM = "custom"  # User-specified count


class ForecastQuery(MiroFishBaseModel):
    """Structured representation of a natural language forecast query.

    This is the output of the NLP parser — everything the pipeline needs
    to know about what the user is asking.
    """

    # What was asked
    raw_query: str  # Original user input
    instrument: str = "ES"  # Parsed instrument symbol
    query_type: QueryType = QueryType.RANGE_FORECAST  # What kind of answer

    # Time parameters
    target_time: str | None = None  # "11:30 AM PT" if specified
    current_time: str | None = None  # User-stated current time if any
    forecast_horizon_minutes: int = 120  # How far ahead to forecast

    # Optional constraints
    target_price: float | None = None  # For probability queries ("will ES hit 5500?")
    direction_bias: str | None = None  # "bullish" / "bearish" if user stated one

    # Additional context extracted from the query
    additional_context: str | None = None  # "before FOMC", "after CPI", etc.
    mentions_event: str | None = None  # Detected event reference

    # Simulation configuration
    sim_preset: SimPreset = SimPreset.STANDARD
    sim_count: int = 200  # Actual number of sims to run

    # Metadata
    parsed_at: datetime | None = None
    parse_method: str | None = None  # "regex" or "llm"


class ForecastSession(MiroFishBaseModel):
    """Tracks the state of an active forecast pipeline."""

    forecast_id: str
    query: ForecastQuery
    status: str = "pending"  # pending, running, complete, error
    current_stage: str = ""
    progress: float = 0.0  # 0.0 to 1.0
    created_at: datetime
    error_message: str | None = None

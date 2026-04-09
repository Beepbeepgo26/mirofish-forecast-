"""Forecast result models — output of the synthesis pipeline."""

from datetime import datetime

from mirofish_forecast.models.base import MiroFishBaseModel


class AgentDecision(MiroFishBaseModel):
    """A single agent's decision for one simulation bar."""

    agent_type: str  # "institutional", "retail", "market_maker"
    direction: str  # "long", "short", "neutral"
    confidence: float  # 0.0 to 1.0
    price_target: float | None = None
    reasoning: str = ""


class SimulationResult(MiroFishBaseModel):
    """Result of a single Monte Carlo simulation run."""

    sim_id: int
    seed: int
    temperature: float
    final_price: float
    price_path: list[float] = []  # Price at each simulated bar
    agent_decisions: list[AgentDecision] = []  # Final bar decisions from each agent
    direction_consensus: str = "neutral"  # Majority direction across agents
    confidence_mean: float = 0.5
    success: bool = True
    error: str | None = None


class ProbabilityDistribution(MiroFishBaseModel):
    """Aggregated probability distribution from Monte Carlo results."""

    median: float
    mean: float
    std_dev: float
    percentile_5: float
    percentile_25: float
    percentile_75: float
    percentile_95: float
    skewness: float
    # Direction probabilities
    prob_up: float  # P(final > current)
    prob_down: float  # P(final < current)
    prob_flat: float  # P(within 0.1% of current)
    # Scenario probabilities (from logarithmic pooling)
    scenario_probs: dict[str, float] = {}  # {"most_probable": 0.55, ...}


class ForecastResult(MiroFishBaseModel):
    """Complete forecast output — the final deliverable."""

    # Identity
    forecast_id: str
    instrument: str
    forecast_horizon_minutes: int
    current_price: float

    # Core forecast
    forecast_text: str  # Plain-English forecast paragraph
    distribution: ProbabilityDistribution

    # Simulation metadata
    total_simulations: int
    successful_simulations: int
    sim_preset: str  # "quick", "standard", "deep", "custom"

    # Top agent reasoning traces (for UI display)
    institutional_reasoning: str = ""
    retail_reasoning: str = ""
    market_maker_reasoning: str = ""

    # Metadata
    created_at: datetime
    pipeline_duration_seconds: float
    build_method: str = "monte_carlo"  # "monte_carlo" or "single_shot"

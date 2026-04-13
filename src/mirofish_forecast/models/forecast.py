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


class CalibrationMetrics(MiroFishBaseModel):
    """Calibration quality metrics applied to this forecast."""

    is_calibrated: bool = False
    calibration_sample_size: int = 0
    expected_coverage: float = 0.90
    observed_coverage: float | None = None
    interval_width_adjustment: float = 0.0
    aci_alpha_current: float = 0.10
    ece: float | None = None


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

    # Calibration (Phase 5)
    calibration: CalibrationMetrics = CalibrationMetrics()


class ForecastTracking(MiroFishBaseModel):
    """Stored record linking a forecast to its actual outcome."""

    forecast_id: str
    instrument: str
    forecast_horizon_minutes: int
    created_at: datetime

    # Predictions at forecast time
    current_price: float
    predicted_median: float
    predicted_p5: float
    predicted_p25: float
    predicted_p75: float
    predicted_p95: float
    predicted_prob_up: float
    predicted_prob_down: float
    predicted_prob_flat: float

    # Calibration features (for CQR training)
    vix_at_forecast: float | None = None
    fear_greed_at_forecast: float | None = None
    agent_disagreement: float = 0.0
    sim_success_rate: float = 1.0
    sim_preset: str = "standard"
    market_regime: str | None = None

    # Actuals (filled in after horizon elapses)
    actual_price: float | None = None
    actual_direction: str | None = None
    actual_return_pct: float | None = None
    outcome_checked: bool = False
    outcome_checked_at: datetime | None = None

    # Scoring (computed after actuals are known)
    p50_hit: bool | None = None
    p90_hit: bool | None = None
    direction_correct: bool | None = None
    absolute_error: float | None = None


class FastPathResult(MiroFishBaseModel):
    """Result from the LightGBM fast path (no Monte Carlo)."""

    forecast_id: str
    instrument: str
    forecast_horizon_minutes: int
    current_price: float

    # Direction probabilities from LightGBM classifier
    prob_up: float
    prob_down: float
    prob_flat: float
    predicted_direction: str  # "up", "down", "flat"
    direction_confidence: float  # max(prob_up, prob_down, prob_flat)

    # Price interval from quantile regressors
    predicted_p5: float  # 5th percentile (lower bound)
    predicted_p95: float  # 95th percentile (upper bound)
    predicted_median: float

    # Natural language forecast
    forecast_text: str

    # Metadata
    feature_count: int
    model_trained_at: str | None = None
    model_sample_size: int = 0
    inference_ms: float
    pipeline_duration_seconds: float
    created_at: datetime
    build_method: str = "fast_path"

    # Calibration (reuse Phase 5)
    calibration: CalibrationMetrics = CalibrationMetrics()

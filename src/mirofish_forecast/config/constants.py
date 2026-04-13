"""Application constants — TTLs, defaults, and magic numbers."""

# Redis cache TTLs (seconds)
CACHE_TTL_OHLCV = 60  # Price data: 1 minute
CACHE_TTL_FRED = 21600  # Macro data: 6 hours
CACHE_TTL_CROSS_ASSET = 300  # Cross-asset correlations: 5 minutes
CACHE_TTL_FEAR_GREED = 900  # Fear & Greed: 15 minutes
CACHE_TTL_VIX_TERM = 300  # VIX term structure: 5 minutes
CACHE_TTL_MARKET_INTERNALS = 30  # TICK/ADD/VOLD: 30 seconds

# Redis key prefixes
CACHE_PREFIX = "mf"

# FRED series IDs
FRED_SERIES_FED_FUNDS = "DFF"
FRED_SERIES_10Y_YIELD = "DGS10"
FRED_SERIES_2Y_YIELD = "DGS2"
FRED_SERIES_10Y_2Y_SPREAD = "T10Y2Y"
FRED_SERIES_VIX_CLOSE = "VIXCLS"
FRED_SERIES_CPI = "CPIAUCSL"  # Raw index — used for YoY fallback calculation
FRED_SERIES_CPI_YOY = "CPALTT01USM657N"  # CPI YoY % change (OECD via FRED)
FRED_SERIES_UNEMPLOYMENT = "UNRATE"
FRED_SERIES_GDP_GROWTH = "A191RL1Q225SBEA"  # Real GDP % change, quarterly, annualized

# yfinance tickers for cross-asset context
YFINANCE_TICKERS = {
    "es": "ES=F",
    "nq": "NQ=F",
    "spy": "SPY",
    "qqq": "QQQ",
    "tlt": "TLT",
    "gld": "GLD",
    "dxy": "DX-Y.NYB",
    "crude": "CL=F",
    "vix": "^VIX",
    "gc": "GC=F",
}

# VIX regime thresholds
VIX_REGIME_COMPLACENT = 15.0
VIX_REGIME_NORMAL = 20.0
VIX_REGIME_ELEVATED = 30.0
# Above 30 = FEAR/CRISIS

# IB relay endpoints
IB_ENDPOINT_TICK = "/api/internals/tick"
IB_ENDPOINT_ADD = "/api/internals/add"
IB_ENDPOINT_VOLD = "/api/internals/vold"

# Data aggregator timeouts (seconds)
DATA_FETCH_TIMEOUT = 10

# --- Phase 2: NLP Parser & Pipeline ---

# Pipeline stage names (used in SSE events)
STAGE_PARSING = "parsing"
STAGE_DATA_COLLECTION = "data_collection"
STAGE_SCENARIO_BUILDING = "scenario_building"  # Phase 3
STAGE_SIMULATION = "simulation"  # Phase 4
STAGE_SYNTHESIS = "synthesis"  # Phase 4
STAGE_COMPLETE = "complete"
STAGE_ERROR = "error"

# Pipeline stage display messages
STAGE_MESSAGES: dict[str, str] = {
    STAGE_PARSING: "Understanding your question...",
    STAGE_DATA_COLLECTION: "Pulling market data...",
    STAGE_SCENARIO_BUILDING: "Building scenarios...",
    STAGE_SIMULATION: "Running simulations...",
    STAGE_SYNTHESIS: "Synthesizing forecast...",
}

# LLM settings
LLM_PARSE_TEMPERATURE = 0.0  # Deterministic parsing
LLM_PARSE_MAX_TOKENS = 500
LLM_PARSE_TIMEOUT = 15  # Seconds

# SSE settings
SSE_KEEPALIVE_INTERVAL = 20  # Seconds between keep-alive comments
SSE_QUEUE_TIMEOUT = 30  # Seconds to wait for next event before keep-alive

# Forecast session settings
FORECAST_SESSION_TTL = 600  # 10 minutes — how long a forecast session lives
MAX_CONCURRENT_FORECASTS = 10  # Max simultaneous forecast pipelines

# Regex patterns for pre-validation
REGEX_INSTRUMENT = r"\b(ES|NQ|CL|GC|YM|RTY|ZB|ZN|SPX|SPY|QQQ)\b"
REGEX_TIME = r"(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?\s*(PT|ET|CT|MT|pt|et|ct|mt|PST|EST|CST|MST)?"
REGEX_HORIZON = r"(\d+)\s*(min(?:ute)?s?|hr?s?|hours?|days?|weeks?)"
REGEX_PRICE_TARGET = r"\$?\b(\d{3,5}(?:\.\d{1,2})?)\b"
REGEX_DIRECTION = r"\b(bullish|bearish|long|short|up|down|rally|sell[-\s]?off|dump|pump|moon)\b"

# Default forecast parameters
DEFAULT_INSTRUMENT = "ES"
DEFAULT_HORIZON_MINUTES = 120  # 2 hours
DEFAULT_SIM_COUNT_QUICK = 100
DEFAULT_SIM_COUNT_STANDARD = 200
DEFAULT_SIM_COUNT_DEEP = 500
DEFAULT_SIM_PRESET = "standard"

# --- Phase 4: Monte Carlo Simulation ---

# Concurrency control
SIM_CONCURRENCY = 20  # Max concurrent simulations
API_CONCURRENCY = 50  # Max concurrent LLM API calls across all sims
WAVE_SIZE = 50  # Simulations per wave
WAVE_PAUSE_SECONDS = 0.2  # semaphore already handles rate limiting; 1.0 was double-protection

# Simulation parameters
SIM_BARS_PER_HORIZON = 20  # Number of price bars to simulate per forecast
SIM_TEMPERATURE_MIN = 0.3  # Min LLM temperature for agent calls
SIM_TEMPERATURE_MAX = 0.9  # Max LLM temperature for agent calls
SIM_MIN_SUCCESS_RATE = 0.70  # Minimum % of sims that must succeed

# Agent types
AGENT_TYPES = ["institutional", "retail", "market_maker"]

# Logarithmic pooling
LOG_POOL_EXTREMIZING_FACTOR = 1.5  # d ≈ 1.5–2.0 (calibrate on historical data)

# Synthesis
SYNTHESIS_MODEL = "gpt-4o-2024-08-06"
SYNTHESIS_TEMPERATURE = 0.4
SYNTHESIS_MAX_TOKENS = 1500
SYNTHESIS_TIMEOUT = 30

# Price target clamping (per bar)
# Max move per bar as a fraction of current price
# At VIX 20, ES moves ~2-3 pts per 6-min bar (~0.05%)
# At VIX 30, ~4-5 pts per bar (~0.08%)
# We allow up to 0.15% per bar to give agents room while preventing runaway drift
SIM_MAX_BAR_MOVE_PCT = 0.0015  # 0.15% max move per bar (~10 pts on ES at 6800)
SIM_DRIFT_ANCHOR_WEIGHT = 0.3  # 30% weight pulling price back toward starting price

# Regime-conditional drift anchor weights — override SIM_DRIFT_ANCHOR_WEIGHT per regime
REGIME_ANCHOR_WEIGHTS = {
    "tight_range": 0.45,
    "volatile_chop": 0.40,
    "trending_up": 0.10,
    "trending_down": 0.10,
    "trend_day_up": 0.05,
    "trend_day_down": 0.05,
    "breakout": 0.15,
    "breakdown": 0.15,
}

# --- Phase 5: Calibration ---

# Forecast tracking
TRACKING_CHECK_DELAY_MINUTES = 5  # Wait N minutes after horizon before checking actuals
TRACKING_MAX_AGE_DAYS = 90  # Keep tracking records for 90 days
TRACKING_STORAGE_PREFIX = "track"  # Redis key prefix (CacheClient adds "mf:" automatically)

# Calibration thresholds
CALIBRATION_MIN_SAMPLES = 200  # Minimum forecasts before CQR activates
CALIBRATION_RETRAIN_INTERVAL = 50  # Retrain CQR model every N new forecasts
CALIBRATION_WINDOW_SIZE = 500  # Use last N forecasts for training

# CQR settings
CQR_QUANTILES = [0.05, 0.25, 0.50, 0.75, 0.95]  # Quantile levels to predict
CQR_ALPHA = 0.10  # Target miscoverage rate (90% coverage)
CQR_CALIBRATION_SPLIT = 0.2  # Hold out 20% for conformal calibration

# ACI settings
ACI_GAMMA = 0.02  # Learning rate for alpha adjustment
ACI_INITIAL_ALPHA = 0.10  # Starting miscoverage rate
ACI_MIN_ALPHA = 0.02  # Don't tighten beyond 98% coverage
ACI_MAX_ALPHA = 0.30  # Don't widen beyond 70% coverage

# Reliability diagram
RELIABILITY_NUM_BINS = 10  # Number of bins for reliability diagram

# --- Multi-Instrument Configuration ---

INSTRUMENT_CONFIG: dict[str, dict] = {
    "ES": {
        "name": "E-mini S&P 500",
        "yfinance_ticker": "ES=F",
        "asset_class": "equity_index",
        "tick_size": 0.25,
        "point_value": 50.0,
        "typical_daily_range": 50,
        "max_bar_move_pct": 0.0015,
        "drift_anchor_weight": 0.3,
        "price_decimals": 2,
        "description": "S&P 500 equity index futures",
        "key_drivers": ("Fed policy, earnings, risk sentiment, VIX, yield curve"),
    },
    "NQ": {
        "name": "E-mini Nasdaq 100",
        "yfinance_ticker": "NQ=F",
        "asset_class": "equity_index",
        "tick_size": 0.25,
        "point_value": 20.0,
        "typical_daily_range": 250,
        "max_bar_move_pct": 0.0020,
        "drift_anchor_weight": 0.3,
        "price_decimals": 2,
        "description": "Nasdaq 100 tech-heavy equity index futures",
        "key_drivers": (
            "Big tech earnings, AI/semiconductor news, growth vs value rotation,"
            " Treasury yields (growth sensitivity)"
        ),
    },
    "CL": {
        "name": "Crude Oil WTI",
        "yfinance_ticker": "CL=F",
        "asset_class": "commodity_energy",
        "tick_size": 0.01,
        "point_value": 1000.0,
        "typical_daily_range": 2.5,
        "max_bar_move_pct": 0.0025,
        "drift_anchor_weight": 0.25,
        "price_decimals": 2,
        "description": "West Texas Intermediate crude oil futures",
        "key_drivers": (
            "OPEC+ production decisions, EIA inventory reports,"
            " geopolitical risk (Middle East), DXY, global demand (China PMI)"
        ),
    },
    "GC": {
        "name": "Gold (COMEX)",
        "yfinance_ticker": "GC=F",
        "asset_class": "commodity_metal",
        "tick_size": 0.10,
        "point_value": 100.0,
        "typical_daily_range": 30,
        "max_bar_move_pct": 0.0020,
        "drift_anchor_weight": 0.25,
        "price_decimals": 2,
        "description": "COMEX gold futures",
        "key_drivers": (
            "Real interest rates (10Y - CPI), DXY inverse correlation,"
            " central bank buying, geopolitical safe-haven flows,"
            " inflation expectations"
        ),
    },
}

SUPPORTED_INSTRUMENTS = list(INSTRUMENT_CONFIG.keys())


def get_instrument_config(instrument: str) -> dict:
    """Get config for an instrument, defaulting to ES if not found."""
    return INSTRUMENT_CONFIG.get(instrument.upper(), INSTRUMENT_CONFIG[DEFAULT_INSTRUMENT])


# --- Market Session Awareness ---

# ES RTH hours (Eastern Time)
RTH_OPEN_HOUR = 9
RTH_OPEN_MINUTE = 30
RTH_CLOSE_HOUR = 16
RTH_CLOSE_MINUTE = 0

# Session classifications
SESSION_RTH = "rth"
SESSION_OVERNIGHT = "overnight"
SESSION_CLOSED = "closed"
SESSION_PRE_MARKET = "pre_market"
SESSION_POST_MARKET = "post_market"

# RTH duration in minutes
RTH_DURATION_MINUTES = 390  # 6.5 hours

# US market holidays 2026 (markets closed)
US_MARKET_HOLIDAYS_2026 = [
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents' Day
    "2026-04-03",  # Good Friday
    "2026-05-25",  # Memorial Day
    "2026-07-03",  # Independence Day (observed)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
]


# --- Economic Calendar ---

FRED_RELEASE_IDS: dict[str, dict] = {
    "CPI": {
        "release_id": 10,
        "name": "Consumer Price Index",
        "typical_time": "08:30 ET",
        "impact": "high",
    },
    "NFP": {
        "release_id": 50,
        "name": "Employment Situation (Nonfarm Payrolls)",
        "typical_time": "08:30 ET",
        "impact": "high",
    },
    "GDP": {
        "release_id": 53,
        "name": "Gross Domestic Product",
        "typical_time": "08:30 ET",
        "impact": "high",
    },
    "PPI": {
        "release_id": 46,
        "name": "Producer Price Index",
        "typical_time": "08:30 ET",
        "impact": "medium",
    },
    "PCE": {
        "release_id": 54,
        "name": "Personal Consumption Expenditures",
        "typical_time": "08:30 ET",
        "impact": "high",
    },
    "RETAIL_SALES": {
        "release_id": 9,
        "name": "Advance Retail Sales",
        "typical_time": "08:30 ET",
        "impact": "medium",
    },
    "ISM_MFG": {
        "release_id": 26,
        "name": "ISM Manufacturing PMI",
        "typical_time": "10:00 ET",
        "impact": "medium",
    },
}

EVENT_IMPACT_VOLATILITY_MULTIPLIER: dict[str, float] = {
    "critical": 2.5,
    "high": 2.0,
    "medium": 1.5,
    "low": 1.0,
}

# Calendar cache TTLs
CACHE_TTL_CALENDAR_TODAY = 3600
CACHE_TTL_CALENDAR_WEEK = 21600
CACHE_TTL_CONSENSUS = 1800

# 2026 FOMC meeting dates (statement release dates)
FOMC_DATES_2026 = [
    "2026-01-28",
    "2026-03-18",
    "2026-04-29",
    "2026-06-17",
    "2026-07-29",
    "2026-09-16",
    "2026-10-28",
    "2026-12-09",
]

FOMC_SEP_DATES_2026 = [
    "2026-03-18",
    "2026-06-17",
    "2026-09-16",
    "2026-12-09",
]

# --- Phase 7: LightGBM Fast Path ---

# Feature extraction
FEATURE_OHLCV_LOOKBACK = 50  # Bars of history for feature computation
FEATURE_VOL_WINDOW = 20  # Rolling window for realized vol
FEATURE_MOMENTUM_WINDOWS = [1, 3, 6, 12]  # Bar lookbacks for returns

# Model storage
ML_MODEL_PREFIX = "ml"
ML_DIRECTION_MODEL_KEY = "ml:direction_model"
ML_QUANTILE_LOW_KEY = "ml:quantile_low_model"
ML_QUANTILE_HIGH_KEY = "ml:quantile_high_model"
ML_FEATURE_NAMES_KEY = "ml:feature_names"
ML_MODEL_METADATA_KEY = "ml:model_metadata"
ML_MODEL_TTL = 86400 * 30  # Models persist 30 days in Redis

# Training
ML_TRAINING_LOOKBACK_DAYS = 365
ML_TRAINING_HORIZONS = [30, 60, 120, 240]
ML_DEFAULT_HORIZON = 120
ML_MIN_TRAINING_SAMPLES = 500
ML_DIRECTION_FLAT_THRESHOLD = 0.001  # 0.1% = flat
ML_TRAIN_STATUS_KEY = "ml:train_status"

# LightGBM hyperparameters
ML_LGBM_DIRECTION_PARAMS: dict = {
    "objective": "multiclass",
    "num_class": 3,
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 200,
    "min_child_samples": 10,
    "verbose": -1,
}

ML_LGBM_QUANTILE_LOW_PARAMS: dict = {
    "objective": "quantile",
    "alpha": 0.05,
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 150,
    "min_child_samples": 10,
    "verbose": -1,
}

ML_LGBM_QUANTILE_HIGH_PARAMS: dict = {
    "objective": "quantile",
    "alpha": 0.95,
    "num_leaves": 31,
    "learning_rate": 0.05,
    "n_estimators": 150,
    "min_child_samples": 10,
    "verbose": -1,
}

# Fast path routing
FAST_PATH_MAX_HORIZON = 240  # Max horizon for fast path (4hr)
FAST_PATH_ELIGIBLE_QUERY_TYPES = [
    "direction_forecast",
    "point_forecast",
]

# Pipeline stage for fast path
STAGE_FAST_INFERENCE = "fast_inference"
STAGE_MESSAGES_FAST = "Running fast inference..."

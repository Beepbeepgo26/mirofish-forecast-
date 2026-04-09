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
FRED_SERIES_CPI = "CPIAUCSL"
FRED_SERIES_UNEMPLOYMENT = "UNRATE"
FRED_SERIES_GDP = "GDP"

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
WAVE_PAUSE_SECONDS = 1.0  # Pause between waves to avoid rate limit bursts

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

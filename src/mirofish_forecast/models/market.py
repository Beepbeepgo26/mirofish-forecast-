from datetime import datetime
from enum import StrEnum

from mirofish_forecast.models.base import MiroFishBaseModel


class VIXRegime(StrEnum):
    COMPLACENT = "complacent"  # < 15
    NORMAL = "normal"  # 15–20
    ELEVATED = "elevated"  # 20–30
    FEAR = "fear"  # > 30


class VIXTermStructure(StrEnum):
    CONTANGO = "contango"  # Normal: front < back
    BACKWARDATION = "backwardation"  # Stress: front > back
    FLAT = "flat"  # Within 0.5 pts


class MacroIndicators(MiroFishBaseModel):
    """FRED-sourced macro data."""

    fed_funds_rate: float | None = None
    ten_year_yield: float | None = None
    two_year_yield: float | None = None
    ten_year_2_year_spread: float | None = None
    vix_close: float | None = None
    cpi_yoy: float | None = None
    unemployment_rate: float | None = None
    gdp_growth: float | None = None
    as_of: datetime | None = None


class VIXData(MiroFishBaseModel):
    """VIX spot and term structure."""

    spot: float | None = None
    regime: VIXRegime | None = None
    front_month: float | None = None
    second_month: float | None = None
    term_structure: VIXTermStructure | None = None
    contango_spread: float | None = None  # second_month - front_month


class CrossAssetSnapshot(MiroFishBaseModel):
    """Cross-asset prices from yfinance."""

    es_price: float | None = None
    nq_price: float | None = None
    spy_price: float | None = None
    qqq_price: float | None = None
    tlt_price: float | None = None
    gld_price: float | None = None
    gc_price: float | None = None
    dxy_price: float | None = None
    crude_price: float | None = None
    vix_price: float | None = None
    as_of: datetime | None = None


class FearGreedData(MiroFishBaseModel):
    """CNN Fear & Greed Index."""

    value: float | None = None  # 0–100
    description: str | None = None  # "Fear", "Extreme Greed", etc.
    last_updated: datetime | None = None


class MarketInternals(MiroFishBaseModel):
    """NYSE market internals from IB relay."""

    nyse_tick: float | None = None  # NYSE TICK index
    nyse_add: float | None = None  # Advance-Decline
    nyse_vold: float | None = None  # Up Volume - Down Volume
    as_of: datetime | None = None


class EconomicEvent(MiroFishBaseModel):
    """A scheduled economic event that may impact markets."""

    name: str  # "CPI", "FOMC", "NFP"
    full_name: str  # "Consumer Price Index"
    date: str  # "2026-04-14"
    time: str | None = None  # "08:30 ET"
    impact: str = "medium"  # "critical", "high", "medium", "low"
    is_today: bool = False
    is_this_week: bool = False
    hours_until: float | None = None  # Negative = already released
    consensus: str | None = None  # "2.8%"
    prior: str | None = None  # "3.0%"
    has_press_conference: bool = False
    has_sep: bool = False  # Summary of Economic Projections
    note: str | None = None


class MarketContext(MiroFishBaseModel):
    """Unified market context assembled from all data sources.

    This is the primary output of the data aggregation layer and the
    primary input to the scenario builder (Phase 3).
    """

    macro: MacroIndicators
    vix: VIXData
    cross_asset: CrossAssetSnapshot
    fear_greed: FearGreedData
    internals: MarketInternals
    events_today: list[EconomicEvent] = []
    events_this_week: list[EconomicEvent] = []
    assembled_at: datetime

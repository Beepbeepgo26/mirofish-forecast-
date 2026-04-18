"""Pre-compute bar analytics for agent prompts.

Thin orchestrator that calls existing signal_bar.py and tod_regime.py modules,
then adds day type classification, Always-In direction, and formatted output.

Computed once per forecast (not per simulation), injected into all agent prompts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from mirofish_forecast.config import constants
from mirofish_forecast.ml.signal_bar import (
    compute_ema,
    extract_bar_features,
    score_signal_bar,
)
from mirofish_forecast.services.tod_regime import get_tod_regime

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


def compute_bar_analytics(
    bars_5m: list[dict],
    is_fomc_day: bool = False,
) -> dict:
    """Compute all analytics from 5-minute bar data.

    Args:
        bars_5m: List of 5-min bar dicts (oldest first), each with
                 keys: time, open, high, low, close, volume.
        is_fomc_day: Whether today has a FOMC announcement.

    Returns:
        Dict with ema_20, signal_score, day_type, always_in, time_phase,
        time_multiplier, bar_number, adr_pct_used, consecutive_trend_bars.
    """
    if not bars_5m or len(bars_5m) < 5:
        return _empty_analytics()

    try:
        closes = [float(b["close"]) for b in bars_5m]
    except (KeyError, TypeError, ValueError):
        return _empty_analytics()

    result: dict = {}

    # --- 20-bar EMA (reuse signal_bar.compute_ema) ---
    ema_val = compute_ema(closes, 20)
    result["ema_20"] = ema_val if ema_val is not None else closes[-1]

    # --- Signal bar score (reuse signal_bar.score_signal_bar) ---
    features = extract_bar_features(bars_5m, current_idx=len(bars_5m) - 1)
    try:
        result["signal_score"] = score_signal_bar(
            bar=bars_5m[-1],
            prior_bar=features.get("prior_bar"),
            ema_20=features.get("ema_20"),
            trend_context=features.get("trend_context", "unknown"),
            avg_bar_range=features.get("avg_bar_range"),
        )
    except (ValueError, KeyError):
        result["signal_score"] = 0

    # --- Day type classification ---
    result["day_type"] = _classify_day_type(bars_5m)

    # --- Always-In direction ---
    result["always_in"] = _determine_always_in(bars_5m, result["ema_20"])

    # --- Time-of-day (reuse tod_regime.get_tod_regime) ---
    regime, multiplier, _ = get_tod_regime(is_fomc_day=is_fomc_day)
    result["time_phase"] = regime.value
    result["time_multiplier"] = multiplier

    # --- RTH bar number ---
    result["bar_number"] = len(_get_todays_rth_bars(bars_5m))

    # --- Consecutive trend bars ---
    result["consecutive_trend_bars"] = _count_consecutive(bars_5m)

    # --- ADR percentage used ---
    result["adr_pct_used"] = _adr_pct_used(bars_5m)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_day_type(bars: list[dict]) -> str:
    """Classify the current day type from RTH bars."""
    rth_bars = _get_todays_rth_bars(bars)

    if len(rth_bars) < 3:
        return "unknown"

    session_open = float(rth_bars[0]["open"])
    session_high = max(float(b["high"]) for b in rth_bars)
    session_low = min(float(b["low"]) for b in rth_bars)
    session_range = session_high - session_low

    if session_range < 0.01:
        return "unknown"

    # Trend From Open: open near the extreme
    open_pct = (session_open - session_low) / session_range
    if open_pct < 0.10:
        return "trend_from_open_bull"
    if open_pct > 0.90:
        return "trend_from_open_bear"

    # Spike & Channel: check EMA slope divergence across session
    if len(rth_bars) >= 10:
        early_closes = [float(b["close"]) for b in rth_bars[:10]]
        late_closes = [float(b["close"]) for b in rth_bars[-10:]]
        early_ema = sum(early_closes) / len(early_closes)
        late_ema = sum(late_closes) / len(late_closes)
        ema_change_pct = abs(late_ema - early_ema) / max(early_ema, 1.0)

        if ema_change_pct > 0.002:
            return "spike_and_channel"

    return "trading_range"


def _determine_always_in(bars: list[dict], ema: float) -> str:
    """Determine Always-In direction from recent bars + EMA."""
    if len(bars) < 10:
        return "neutral"

    recent = bars[-10:]
    above_ema = sum(1 for b in recent if float(b["close"]) > ema)
    below_ema = sum(1 for b in recent if float(b["close"]) < ema)

    # Check EMA slope
    if len(bars) >= 25:
        ema_now = compute_ema([float(b["close"]) for b in bars], 20)
        ema_5_ago = compute_ema([float(b["close"]) for b in bars[:-5]], 20)
        if ema_now is not None and ema_5_ago is not None:
            ema_slope = ema_now - ema_5_ago
        else:
            ema_slope = 0.0
    else:
        ema_slope = 0.0

    if above_ema >= 7 and ema_slope > 0:
        return "long"
    if below_ema >= 7 and ema_slope < 0:
        return "short"

    return "neutral"


def _count_consecutive(bars: list[dict]) -> int:
    """Count consecutive bars in the same direction (from newest).

    Returns:
        Positive int = bullish streak, negative int = bearish streak.
    """
    if len(bars) < 2:
        return 0

    last_close = float(bars[-1]["close"])
    last_open = float(bars[-1]["open"])
    direction = 1 if last_close > last_open else -1
    count = 1

    for i in range(len(bars) - 2, max(0, len(bars) - 21), -1):
        bar_dir = 1 if float(bars[i]["close"]) > float(bars[i]["open"]) else -1
        if bar_dir == direction:
            count += 1
        else:
            break

    return count * direction


def _adr_pct_used(bars: list[dict]) -> float:
    """Calculate what % of average daily range has been used today."""
    rth_bars = _get_todays_rth_bars(bars)
    if len(rth_bars) < 2:
        return 0.0

    today_range = (
        max(float(b["high"]) for b in rth_bars)
        - min(float(b["low"]) for b in rth_bars)
    )

    # Estimate ADR from available bars
    recent = bars[-78:] if len(bars) >= 78 else bars
    avg_bar_range = (
        sum(float(b["high"]) - float(b["low"]) for b in recent) / len(recent)
    )
    estimated_adr = avg_bar_range * 78  # Full RTH session

    if estimated_adr < 0.01:
        return 0.0

    return round(min(today_range / estimated_adr, 2.0), 2)


def _get_todays_rth_bars(bars: list[dict]) -> list[dict]:
    """Filter bars to today's RTH session only."""
    now_et = datetime.now(ET)
    today = now_et.date()
    rth_bars: list[dict] = []

    for bar in bars:
        try:
            bar_dt = datetime.fromtimestamp(
                int(bar["time"]), tz=timezone.utc
            ).astimezone(ET)
            bar_date = bar_dt.date()
            bar_minutes = bar_dt.hour * 60 + bar_dt.minute

            if (
                bar_date == today
                and constants.RTH_START_MINUTES
                <= bar_minutes
                < constants.RTH_END_MINUTES
            ):
                rth_bars.append(bar)
        except Exception:
            continue

    return rth_bars


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_analytics_for_prompt(analytics: dict) -> str:
    """Format pre-computed analytics as text for agent prompts."""
    score = analytics.get("signal_score", 0)
    if score >= constants.SIGNAL_SCORE_HIGH_CONVICTION:
        score_label = "HIGH CONVICTION"
    elif score >= constants.SIGNAL_SCORE_MODERATE:
        score_label = "MODERATE"
    else:
        score_label = "LOW — CAUTION"

    consec = analytics.get("consecutive_trend_bars", 0)
    consec_str = (
        f"{abs(consec)} {'bullish' if consec > 0 else 'bearish'}"
        if consec != 0
        else "0"
    )

    lines = [
        "=== PRE-COMPUTED BAR ANALYTICS ===",
        f"20-bar EMA: {analytics.get('ema_20', 'N/A')}",
        f"Signal Bar Score: {score}/100 ({score_label})",
        f"Day Type: {analytics.get('day_type', 'unknown').replace('_', ' ').upper()}",
        f"Always-In Direction: {analytics.get('always_in', 'neutral').upper()}",
        f"Time Phase: {analytics.get('time_phase', 'unknown').replace('_', ' ').title()}"
        f" (confidence multiplier: {analytics.get('time_multiplier', 1.0):.2f})",
        f"RTH Bar #: {analytics.get('bar_number', 0)} of 78",
        f"ADR Used: {analytics.get('adr_pct_used', 0) * 100:.0f}%",
        f"Consecutive Trend Bars: {consec_str}",
    ]
    return "\n".join(lines)


def _empty_analytics() -> dict:
    """Return empty analytics dict for insufficient data."""
    return {
        "ema_20": 0.0,
        "signal_score": 0,
        "day_type": "unknown",
        "always_in": "neutral",
        "time_phase": "unknown",
        "time_multiplier": 1.0,
        "bar_number": 0,
        "consecutive_trend_bars": 0,
        "adr_pct_used": 0.0,
    }

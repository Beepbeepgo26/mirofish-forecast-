"""Al Brooks signal bar scoring rubric — 0 to 100.

Translates Brooks' qualitative criteria ("strong", "reasonable", "weak") into a
deterministic numerical score that can be injected into LLM agent prompts as a
quantitative anchor. Sub-millisecond — pure Python math, no LLM required.

Score interpretation:
    70–100  High-conviction signal — take with standard size
    50–69   Context-dependent — requires additional confluence
    30–49   Weak — needs overwhelming context
    <30     Do not act on this bar alone

Reference: Al Brooks, "Price Action Trading" (all three volumes)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def score_signal_bar(
    bar: dict,
    prior_bar: dict | None = None,
    ema_20: float | None = None,
    trend_context: str = "unknown",
    is_second_entry: bool = False,
    avg_bar_range: float | None = None,
) -> int:
    """Score a 5-minute bar on the Al Brooks signal bar rubric (0–100).

    Args:
        bar: OHLCV dict with keys: open, high, low, close, volume.
        prior_bar: The immediately preceding bar (for overlap scoring).
        ema_20: Current 20-period EMA value.
        trend_context: One of "strong_trend", "channel", "trading_range",
                       "counter_trend", or "unknown".
        is_second_entry: True if this is an H2/L2 entry pattern (per Brooks).
        avg_bar_range: Rolling average of recent bar ranges (for bar size scoring).

    Returns:
        Integer score 0–100.

    Raises:
        ValueError: If bar data is missing required OHLCV keys.
    """
    try:
        o = float(bar["open"])
        h = float(bar["high"])
        l = float(bar["low"])
        c = float(bar["close"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"bar must contain open/high/low/close — {exc}") from exc

    bar_range = h - l
    if bar_range <= 0:
        return 0  # Zero-range bar — degenerate, no signal

    body = abs(c - o)
    is_bullish = c >= o

    score = 0

    # --- Criterion 1: Body-to-Range Ratio (25 pts) ---
    body_ratio = body / bar_range
    if body_ratio > 0.66:
        score += 25
    elif body_ratio >= 0.50:
        score += 20
    elif body_ratio >= 0.33:
        score += 12
    # else: doji — 0 pts

    # --- Criterion 2: Close Location (20 pts) ---
    # Close in correct half = bullish bar closes in top half, bearish in bottom half
    # "Correct direction" = close position matches body direction
    if is_bullish:
        close_pct = (c - l) / bar_range  # 1.0 = closed at high
    else:
        close_pct = (h - c) / bar_range  # 1.0 = closed at low (for bearish)

    if close_pct >= 0.75:
        score += 20
    elif close_pct >= 0.50:
        score += 12
    elif close_pct >= 0.25:
        score += 4
    # else: closed in wrong quarter — 0 pts

    # --- Criterion 3: Tail Quality (15 pts) ---
    # Good signal bar: rejection tail (⅓–½ range) opposite to direction, small same-side tail
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if is_bullish:
        rejection_tail = lower_wick  # Good: small lower wick (demand absorbed sellers)
        wrong_side_tail = upper_wick  # Bad: large upper wick (supply rejected buyers)
    else:
        rejection_tail = upper_wick  # Good: small upper wick (supply absorbed buyers)
        wrong_side_tail = lower_wick  # Bad: large lower wick (demand rejected sellers)

    rejection_ratio = rejection_tail / bar_range
    wrong_ratio = wrong_side_tail / bar_range

    # Ideal: rejection tail 0.10–0.25 of range (entry absorbed), minimal wrong-side tail
    if rejection_ratio <= 0.25 and wrong_ratio <= 0.15:
        score += 15  # Clean bar, minimal wicks
    elif rejection_ratio <= 0.33 and wrong_ratio <= 0.25:
        score += 10  # Acceptable tail structure
    elif wrong_ratio > 0.40:
        score += 0   # Large wrong-side tail — bad signal
    else:
        score += 5   # Mixed tail quality

    # --- Criterion 4: Prior Bar Overlap (10 pts) ---
    if prior_bar is not None:
        try:
            ph = float(prior_bar["high"])
            pl = float(prior_bar["low"])
            prior_range = ph - pl

            if prior_range > 0:
                # Overlap: how much of this bar's range is inside prior bar's range
                overlap_low = max(l, pl)
                overlap_high = min(h, ph)
                overlap = max(0.0, overlap_high - overlap_low)
                overlap_ratio = overlap / bar_range

                if overlap_ratio < 0.10:
                    score += 10  # Gap or minimal overlap — strong breakout
                elif overlap_ratio < 0.40:
                    score += 5   # Some overlap — acceptable
                # else: heavy overlap — 0 pts (inside bar / small breakout)
        except (KeyError, TypeError, ValueError):
            pass  # Missing prior bar data — skip criterion

    # --- Criterion 5: EMA-20 Relationship (10 pts) ---
    if ema_20 is not None:
        ema_dist = abs(c - ema_20)
        # "At the EMA" = within 1 average bar range of the EMA
        ema_bar_units = (avg_bar_range or bar_range)

        if ema_dist <= 0.3 * ema_bar_units:
            score += 10  # Touching/kissing EMA — classic entry point
        elif ema_dist <= 1.0 * ema_bar_units:
            score += 6   # Within 1 bar range of EMA
        else:
            score += 2   # Far from EMA — less ideal

    # --- Criterion 6: Trend Context (10 pts) ---
    context_scores = {
        "strong_trend": 10,
        "channel": 7,
        "trading_range": 3,
        "counter_trend": 0,
        "unknown": 5,
    }
    score += context_scores.get(trend_context, 5)

    # --- Criterion 7: Bar Size (5 pts) ---
    if avg_bar_range is not None and avg_bar_range > 0:
        size_ratio = bar_range / avg_bar_range
        if 0.75 <= size_ratio <= 1.75:
            score += 5   # Average or slightly above — ideal signal bar
        elif size_ratio > 2.5:
            score += 2   # Climactic / spike bar — often reverses
        else:
            score += 1   # Tiny bar — little commitment
    else:
        score += 3  # No reference — neutral

    # --- Criterion 8: Second Entry / H2-L2 (5 pts) ---
    if is_second_entry:
        score += 5
    # else first entry = 0 pts (not penalized, just not rewarded)

    return min(100, max(0, score))


def describe_signal_score(score: int) -> str:
    """Return a brief text label for a signal bar score."""
    if score >= 70:
        return f"{score}/100 — HIGH CONVICTION (take with standard size)"
    elif score >= 50:
        return f"{score}/100 — MODERATE (needs confluence)"
    elif score >= 30:
        return f"{score}/100 — WEAK (needs overwhelming context)"
    else:
        return f"{score}/100 — DO NOT ACT (poor signal bar)"


def compute_ema(prices: list[float], period: int = 20) -> float | None:
    """Compute EMA from a list of closing prices.

    Args:
        prices: Recent closing prices, oldest first.
        period: EMA period (default 20).

    Returns:
        Current EMA value, or None if insufficient data.
    """
    if len(prices) < period:
        return None

    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period  # SMA seed
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return round(ema, 2)


def extract_bar_features(
    bars: list[dict],
    current_idx: int = -1,
) -> dict:
    """Extract derived features from a bar list for signal scoring.

    Args:
        bars: List of OHLCV bar dicts, oldest first.
        current_idx: Index of the bar to evaluate (-1 = last).

    Returns:
        Dict with keys: ema_20, avg_bar_range, prior_bar, trend_context.
    """
    if not bars:
        return {}

    idx = current_idx if current_idx >= 0 else len(bars) - 1
    closes = [float(b["close"]) for b in bars[: idx + 1]]
    ranges = [float(b["high"]) - float(b["low"]) for b in bars[: idx + 1]]

    ema_20 = compute_ema(closes)
    avg_range = sum(ranges[-20:]) / len(ranges[-20:]) if ranges else None
    prior_bar = bars[idx - 1] if idx > 0 else None

    # Infer trend context from EMA slope and bar positions
    trend_context = "unknown"
    if ema_20 is not None and len(closes) >= 5:
        recent_closes = closes[-5:]
        above_ema = sum(1 for c in recent_closes if c > ema_20)
        if above_ema >= 4:
            trend_context = "strong_trend" if closes[-1] > closes[-5] else "channel"
        elif above_ema <= 1:
            trend_context = "counter_trend"
        else:
            trend_context = "trading_range"

    return {
        "ema_20": ema_20,
        "avg_bar_range": avg_range,
        "prior_bar": prior_bar,
        "trend_context": trend_context,
    }

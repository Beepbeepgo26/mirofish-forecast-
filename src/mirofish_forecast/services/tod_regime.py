"""Time-of-Day Regime Classifier for ES futures.

Returns the current session phase and a confidence multiplier that all three agents
apply to their stated confidence. Based on the U-shaped volume curve and empirical
ES intraday behavior documented in the multi-agent framework research.

Regime schedule (all times Eastern):
    9:30–10:30  Opening Rotation   — highest volume & signal reliability
    10:30–11:30 Trend Establishment — programs activate, morning ambiguity resolves
    11:30–13:30 Lunch Doldrums     — multiplier 0.50, mean-reversion dominates
    13:30–14:00 Pre-Breakout       — range compression before afternoon move
    14:00–14:45 Prime Breakout     — range-bound breakouts deserve respect
    15:00–16:00 Power Hour         — volume surge, MOC-driven
    Outside RTH Overnight          — reduced confidence
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


class TODRegime(str, Enum):
    """Time-of-day regime names."""

    OPENING_ROTATION = "opening_rotation"    # 9:30–10:30
    TREND_ESTABLISH = "trend_establish"      # 10:30–11:30
    LUNCH_DOLDRUMS = "lunch_doldrums"        # 11:30–13:30
    PRE_BREAKOUT = "pre_breakout"            # 13:30–14:00
    PRIME_BREAKOUT = "prime_breakout"        # 14:00–14:45
    FOMC_WINDOW = "fomc_window"              # 14:00–14:45 on FOMC days
    POWER_HOUR = "power_hour"               # 15:00–16:00
    OVERNIGHT = "overnight"                  # Outside RTH


_REGIME_CONFIG: dict[TODRegime, dict] = {
    TODRegime.OPENING_ROTATION: {
        "label": "Opening Rotation (9:30–10:30 ET)",
        "confidence_multiplier": 0.85,
        "notes": (
            "Highest volume but directional noise is high — 50% of strong opening "
            "moves fail and reverse. Wait for IB to form before assigning high conviction."
        ),
    },
    TODRegime.TREND_ESTABLISH: {
        "label": "Trend Establishment (10:30–11:30 ET)",
        "confidence_multiplier": 1.00,
        "notes": (
            "Transitional programs activate at the 10:00 AM turn. "
            "Morning ambiguity typically resolves. Economic data at 10:00 AM "
            "(ISM, consumer confidence) can drive sharp moves."
        ),
    },
    TODRegime.LUNCH_DOLDRUMS: {
        "label": "Lunch Doldrums (11:30 AM–1:30 PM ET)",
        "confidence_multiplier": 0.50,
        "notes": (
            "Volume bottoms near 12:56 PM ET (~6–8% of daily volume). "
            "Mean-reversion dominates — false breakouts spike, follow-through is rare. "
            "European close at 11:30 AM creates mini-inflection. REDUCE all targets."
        ),
    },
    TODRegime.PRE_BREAKOUT: {
        "label": "Pre-Breakout Window (1:30–2:00 PM ET)",
        "confidence_multiplier": 0.90,
        "notes": (
            "Compression window before the 2:00 PM breakout attempt. "
            "Range contracting — avoid chasing moves."
        ),
    },
    TODRegime.PRIME_BREAKOUT: {
        "label": "Prime Breakout Window (2:00–2:45 PM ET)",
        "confidence_multiplier": 1.10,
        "notes": (
            "If range-bound all morning, breakouts in this window deserve maximum respect. "
            "FOMC at 2:00 PM overrides all other patterns — assign near-zero confidence "
            "to the initial 2:00 PM FOMC spike direction (reverses 60–70% by close)."
        ),
    },
    TODRegime.FOMC_WINDOW: {
        "label": "FOMC Announcement Window (2:00–2:45 PM ET)",
        "confidence_multiplier": 0.40,
        "notes": (
            "FOMC days follow a four-stage pattern: pre-announcement compression (30–50% "
            "of normal range), initial 2:00 PM spike (0.8–1.5% within 90 seconds, "
            "reversed 60–70% by close), true move after 2:30 PM press conference. "
            "ASSIGN NEAR-ZERO confidence to the initial spike direction."
        ),
    },
    TODRegime.POWER_HOUR: {
        "label": "Power Hour (3:00–4:00 PM ET)",
        "confidence_multiplier": 1.05,
        "notes": (
            "Volume surges toward close. Countertrend inflection often near 3:00–3:10 PM "
            "(linked to old bond pit close). At 3:50 PM, NYSE publishes MOC imbalance data "
            "— drives the final 10-minute directional push with high reliability. "
            "Institutional agent should weight MOC imbalance heavily if $1B+."
        ),
    },
    TODRegime.OVERNIGHT: {
        "label": "Overnight Session",
        "confidence_multiplier": 0.70,
        "notes": (
            "Outside RTH. Reduced liquidity, wider spreads. "
            "International flow (Asia/Europe sessions) shapes overnight range. "
            "Key overnight high/low will establish reference levels for morning open."
        ),
    },
}


def get_tod_regime(
    now: datetime | None = None,
    is_fomc_day: bool = False,
) -> tuple[TODRegime, float, str]:
    """Determine the current time-of-day regime and confidence multiplier.

    Args:
        now: Datetime to evaluate (defaults to current time in ET).
        is_fomc_day: If True, override 14:00–14:45 ET with FOMC_WINDOW regime.

    Returns:
        Tuple of (TODRegime, confidence_multiplier, notes_string).
    """
    if now is None:
        now = datetime.now(ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    else:
        now = now.astimezone(ET)

    hour = now.hour
    minute = now.minute
    minutes = hour * 60 + minute

    # RTH: 9:30 AM (570) to 16:00 (960) ET
    if minutes < 570 or minutes >= 960:
        regime = TODRegime.OVERNIGHT
    elif minutes < 630:   # 9:30–10:30
        regime = TODRegime.OPENING_ROTATION
    elif minutes < 690:   # 10:30–11:30
        regime = TODRegime.TREND_ESTABLISH
    elif minutes < 810:   # 11:30–13:30
        regime = TODRegime.LUNCH_DOLDRUMS
    elif minutes < 840:   # 13:30–14:00
        regime = TODRegime.PRE_BREAKOUT
    elif minutes < 885:   # 14:00–14:45
        regime = TODRegime.FOMC_WINDOW if is_fomc_day else TODRegime.PRIME_BREAKOUT
    elif minutes < 900:   # 14:45–15:00 — transition, treat as pre-power
        regime = TODRegime.PRE_BREAKOUT
    else:                 # 15:00–16:00
        regime = TODRegime.POWER_HOUR

    config = _REGIME_CONFIG[regime]
    return regime, config["confidence_multiplier"], config["notes"]


def format_tod_context(
    now: datetime | None = None,
    is_fomc_day: bool = False,
    minutes_to_close: int | None = None,
) -> str:
    """Format time-of-day context as a text block for agent prompts.

    Args:
        now: Datetime to evaluate (defaults to current ET time).
        is_fomc_day: Whether today has a FOMC announcement.
        minutes_to_close: Minutes remaining until RTH close (for last-hour context).

    Returns:
        Multi-line string suitable for embedding in agent prompts.
    """
    regime, multiplier, notes = get_tod_regime(now, is_fomc_day)
    config = _REGIME_CONFIG[regime]

    lines = [
        "=== TIME-OF-DAY REGIME ===",
        f"Current Phase: {config['label']}",
        f"Confidence Multiplier: {multiplier:.0%} (multiply your stated confidence by this)",
        f"Context: {notes}",
    ]

    if minutes_to_close is not None and minutes_to_close <= 60:
        lines.append(
            f"⚠ {minutes_to_close} minutes to RTH close — "
            "gamma exposure peaks, 0DTE strike battles intensify."
        )

    if multiplier <= 0.50:
        lines.append(
            "⚠ LOW CONFIDENCE WINDOW — tighten all price targets, "
            "avoid chasing breakouts."
        )

    return "\n".join(lines)

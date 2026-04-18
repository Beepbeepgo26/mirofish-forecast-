"""Computes key session reference levels from 5-minute bar data.

Every ES trader watches these levels:
1. Prior Day RTH High / Low / Close (PDH / PDL / PDC)
2. Overnight High / Low (ONH / ONL)
3. Today's RTH Open
4. VWAP (Volume-Weighted Average Price, anchored to RTH open)
5. Initial Balance High / Low (first 60 min of RTH)
"""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from mirofish_forecast.config import constants

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")


def compute_session_levels(bars_5m: list[dict]) -> dict:
    """Compute all session reference levels from 5-minute bars.

    Args:
        bars_5m: List of 5-minute bar dicts with time, open, high, low, close, volume.
                 Should cover at least today + yesterday (150+ bars).

    Returns:
        Dict with keys:
            prior_rth_high, prior_rth_low, prior_rth_close,
            overnight_high, overnight_low,
            today_rth_open, today_rth_high, today_rth_low,
            vwap, vwap_upper, vwap_lower,
            ib_high, ib_low, ib_range,
            current_bar_number (within RTH session)
    """
    if not bars_5m or len(bars_5m) < 20:
        return _empty_levels()

    try:
        now_et = datetime.now(ET)
        today = now_et.date()

        # Classify bars by session
        today_rth: list[dict] = []
        prior_rth: list[dict] = []
        overnight: list[dict] = []

        for bar in bars_5m:
            bar_dt = datetime.fromtimestamp(
                bar["time"], tz=timezone.utc
            ).astimezone(ET)
            bar_date = bar_dt.date()
            bar_mins = bar_dt.hour * 60 + bar_dt.minute
            is_rth = (
                constants.RTH_START_MINUTES <= bar_mins < constants.RTH_END_MINUTES
            )
            is_weekday = bar_dt.weekday() < 5

            if bar_date == today and is_rth and is_weekday:
                today_rth.append(bar)
            elif bar_date == today and not is_rth:
                overnight.append(bar)
            elif is_rth and is_weekday:
                prior_rth.append(bar)
            else:
                overnight.append(bar)

        levels: dict[str, float | int | None] = {}

        # Prior Day RTH
        if prior_rth:
            levels["prior_rth_high"] = round(max(b["high"] for b in prior_rth), 2)
            levels["prior_rth_low"] = round(min(b["low"] for b in prior_rth), 2)
            levels["prior_rth_close"] = round(prior_rth[-1]["close"], 2)
        else:
            levels["prior_rth_high"] = None
            levels["prior_rth_low"] = None
            levels["prior_rth_close"] = None

        # Overnight
        if overnight:
            levels["overnight_high"] = round(max(b["high"] for b in overnight), 2)
            levels["overnight_low"] = round(min(b["low"] for b in overnight), 2)
        else:
            levels["overnight_high"] = None
            levels["overnight_low"] = None

        # Today RTH
        if today_rth:
            levels["today_rth_open"] = round(today_rth[0]["open"], 2)
            levels["today_rth_high"] = round(max(b["high"] for b in today_rth), 2)
            levels["today_rth_low"] = round(min(b["low"] for b in today_rth), 2)

            # VWAP: Σ(TP × Volume) / Σ(Volume), TP = (H+L+C)/3
            tp_vol_sum = 0.0
            vol_sum = 0.0
            tp_vol_sq_sum = 0.0
            for b in today_rth:
                tp = (b["high"] + b["low"] + b["close"]) / 3
                vol = b.get("volume", 0)
                tp_vol_sum += tp * vol
                vol_sum += vol
                tp_vol_sq_sum += (tp ** 2) * vol

            if vol_sum > 0:
                vwap = tp_vol_sum / vol_sum
                # Standard deviation bands
                variance = (tp_vol_sq_sum / vol_sum) - (vwap ** 2)
                std = variance ** 0.5 if variance > 0 else 0
                levels["vwap"] = round(vwap, 2)
                levels["vwap_upper"] = round(vwap + std, 2)
                levels["vwap_lower"] = round(vwap - std, 2)
            else:
                levels["vwap"] = None
                levels["vwap_upper"] = None
                levels["vwap_lower"] = None

            # Initial Balance (first 12 five-minute bars = 60 minutes)
            ib_bars = today_rth[: constants.INITIAL_BALANCE_BARS]
            if ib_bars:
                levels["ib_high"] = round(max(b["high"] for b in ib_bars), 2)
                levels["ib_low"] = round(min(b["low"] for b in ib_bars), 2)
                levels["ib_range"] = round(
                    levels["ib_high"] - levels["ib_low"], 2
                )
            else:
                levels["ib_high"] = None
                levels["ib_low"] = None
                levels["ib_range"] = None

            # Current bar number in RTH session
            levels["current_bar_number"] = len(today_rth)
        else:
            levels["today_rth_open"] = None
            levels["today_rth_high"] = None
            levels["today_rth_low"] = None
            levels["vwap"] = None
            levels["vwap_upper"] = None
            levels["vwap_lower"] = None
            levels["ib_high"] = None
            levels["ib_low"] = None
            levels["ib_range"] = None
            levels["current_bar_number"] = 0

        return levels

    except Exception:
        logger.error("Failed to compute session levels", exc_info=True)
        return _empty_levels()


def format_session_levels_text(levels: dict) -> str:
    """Format session levels as readable text for agent prompts."""
    lines = ["SESSION REFERENCE LEVELS:"]

    if levels.get("prior_rth_high") is not None:
        lines.append(
            f"  Prior Day RTH: H {levels['prior_rth_high']:.2f} "
            f"/ L {levels['prior_rth_low']:.2f} "
            f"/ C {levels['prior_rth_close']:.2f}"
        )

    if levels.get("overnight_high") is not None:
        lines.append(
            f"  Overnight:     H {levels['overnight_high']:.2f} "
            f"/ L {levels['overnight_low']:.2f}"
        )

    if levels.get("today_rth_open") is not None:
        lines.append(f"  Today Open:    {levels['today_rth_open']:.2f}")
        lines.append(
            f"  Today Range:   H {levels['today_rth_high']:.2f} "
            f"/ L {levels['today_rth_low']:.2f}"
        )

    if levels.get("vwap") is not None:
        lines.append(
            f"  VWAP:          {levels['vwap']:.2f} "
            f"(bands: {levels['vwap_lower']:.2f} – {levels['vwap_upper']:.2f})"
        )

    if levels.get("ib_high") is not None:
        lines.append(
            f"  Initial Bal:   H {levels['ib_high']:.2f} "
            f"/ L {levels['ib_low']:.2f} "
            f"(range: {levels['ib_range']:.2f})"
        )

    if levels.get("current_bar_number", 0) > 0:
        lines.append(
            f"  RTH Bar #:     {levels['current_bar_number']} of 78"
        )

    if len(lines) == 1:
        return "SESSION REFERENCE LEVELS: Not available (market may be closed)"

    return "\n".join(lines)


def format_bars_for_agents(bars: list[dict], max_bars: int = 50) -> str:
    """Format OHLCV bars as readable text for agent prompts.

    Shows the most recent bars with directional indicators.
    """
    if not bars:
        return "RECENT PRICE BARS: Not available"

    display = bars[-max_bars:]
    lines = [f"RECENT 5-MINUTE BARS ({len(display)} bars, newest last):"]

    for b in display:
        change = b["close"] - b["open"]
        direction = "▲" if change > 0 else "▼" if change < 0 else "—"
        rng = b["high"] - b["low"]
        body_pct = abs(change) / max(rng, 0.01) * 100

        lines.append(
            f"  {direction} O:{b['open']:.2f} H:{b['high']:.2f} "
            f"L:{b['low']:.2f} C:{b['close']:.2f} "
            f"V:{b.get('volume', 0):,} "
            f"(rng:{rng:.2f} body:{body_pct:.0f}%)"
        )

    return "\n".join(lines)


def _empty_levels() -> dict:
    """Return empty session levels dict."""
    return {
        "prior_rth_high": None, "prior_rth_low": None, "prior_rth_close": None,
        "overnight_high": None, "overnight_low": None,
        "today_rth_open": None, "today_rth_high": None, "today_rth_low": None,
        "vwap": None, "vwap_upper": None, "vwap_lower": None,
        "ib_high": None, "ib_low": None, "ib_range": None,
        "current_bar_number": 0,
    }

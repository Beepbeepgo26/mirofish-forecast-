"""Market maker agent context block template.

Role: Delta-hedging dealer. GEX regime determines behavioral rules — not opinion.

Supplementary data exclusive to this agent (not shared with institutional or retail):
- GEX regime: positive (mean-revert) vs negative (follow momentum)
- Key GEX levels: Call Wall, Put Wall, Zero Gamma, Volatility Trigger
- 0DTE dynamics: last-90-minute amplification, strike battles
- Expiration calendar: OPEX week charm/vanna flows vs post-OPEX unclenched ranges
- Market internals: NYSE TICK/ADD/VOLD
"""

from mirofish_forecast.config.constants import get_instrument_config


def build_market_maker_context_template(
    instrument: str = "ES",
    nyse_tick: float | None = None,
    nyse_add: float | None = None,
    nyse_vold: float | None = None,
    vix_spot: float | None = None,
    es_price: float | None = None,
    # GEX regime context (from SpotGamma/OptionMetrics — None until connected)
    gex_regime: str | None = None,  # "positive" | "negative" | None
    gex_magnitude: float | None = None,  # $ billions of aggregate GEX
    call_wall: float | None = None,  # Highest gamma from calls (intraday resistance ceiling)
    put_wall: float | None = None,  # Highest gamma from puts (intraday support floor)
    zero_gamma: float | None = None,  # Gamma flip level (regime boundary)
    vol_trigger: float | None = None,  # Volatility trigger level (range expansion warning)
    # Expiration context
    is_opex_week: bool = False,  # Monthly OPEX week (charm/vanna tailwinds)
    is_post_opex: bool = False,  # First two sessions post-OPEX (unclenched ranges)
    days_to_opex: int | None = None,
    # 0DTE context
    minutes_to_close: int | None = None,  # For last-90-min amplification warnings
) -> str:
    """Build a deterministic market maker context block from raw values."""
    config = get_instrument_config(instrument)

    def fmt(val: float | None, decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}"

    def fmtb(val: float | None) -> str:
        if val is None:
            return "N/A"
        return f"${val:.1f}B"

    # TICK interpretation
    tick_signal = "N/A"
    if nyse_tick is not None:
        if nyse_tick > 500:
            tick_signal = f"{nyse_tick:+.0f} — Strong buying pressure, aggressive uptick"
        elif nyse_tick > 200:
            tick_signal = f"{nyse_tick:+.0f} — Mild buying pressure"
        elif nyse_tick > -200:
            tick_signal = f"{nyse_tick:+.0f} — Neutral/balanced flow"
        elif nyse_tick > -500:
            tick_signal = f"{nyse_tick:+.0f} — Mild selling pressure"
        else:
            tick_signal = f"{nyse_tick:+.0f} — Strong selling pressure, aggressive downtick"

    # ADD interpretation
    add_signal = "N/A"
    if nyse_add is not None:
        if nyse_add > 1000:
            add_signal = f"{nyse_add:+.0f} — Broad-based buying, strong breadth"
        elif nyse_add > 0:
            add_signal = f"{nyse_add:+.0f} — Mildly positive breadth"
        elif nyse_add > -1000:
            add_signal = f"{nyse_add:+.0f} — Mildly negative breadth"
        else:
            add_signal = f"{nyse_add:+.0f} — Broad-based selling, weak breadth"

    # VOLD interpretation
    vold_signal = "N/A"
    if nyse_vold is not None:
        if nyse_vold > 0:
            vold_signal = f"{nyse_vold:+.0f}M — Up volume dominates (buying conviction)"
        else:
            vold_signal = f"{nyse_vold:+.0f}M — Down volume dominates (selling conviction)"

    # GEX regime block
    gex_lines = ["=== GAMMA EXPOSURE (GEX) REGIME ==="]
    if gex_regime is not None:
        if gex_regime.lower() == "positive":
            gex_lines += [
                f"GEX Regime: POSITIVE ({fmtb(gex_magnitude)}) — MEAN-REVERSION environment",
                "Dealer behavior: BUY dips, SELL rallies to maintain delta neutrality.",
                "Expected daily range: 15–40 ES pts. FADE moves at GEX walls.",
                "Strategy: Tighten targets, assign higher confidence to reversal setups.",
                f"  Call Wall (resistance ceiling): {fmt(call_wall)}",
                f"  Put Wall (support floor):       {fmt(put_wall)}",
                f"  Zero Gamma (regime boundary):   {fmt(zero_gamma)}",
                f"  Volatility Trigger:             {fmt(vol_trigger)}",
                (
                    f"First price target = nearest GEX wall ({fmt(call_wall)} resistance or "
                    f"{fmt(put_wall)} support)."
                ),
            ]
        elif gex_regime.lower() == "negative":
            gex_lines += [
                f"GEX Regime: NEGATIVE ({fmtb(gex_magnitude)}) — MOMENTUM/TRENDING environment",
                "Dealer behavior: SELL into dips, BUY into rallies — AMPLIFIES directional moves.",
                "Expected daily range: 50–120+ ES pts. ALL large intraday moves occur during negative GEX.",
                "Strategy: Follow momentum, AVOID fading moves, widen targets by 20%.",
                f"  Call Wall (resistance target): {fmt(call_wall)} + 20% extension for momentum overshoot",
                f"  Put Wall (support target):     {fmt(put_wall)} + 20% extension for downside",
                f"  Zero Gamma (regime boundary):  {fmt(zero_gamma)}",
                f"  Volatility Trigger:            {fmt(vol_trigger)}",
            ]
    else:
        gex_lines += [
            "GEX Data: NOT AVAILABLE (GEX provider not connected)",
            "Fallback Regime Inference from VIX:",
        ]
        if vix_spot is not None:
            if vix_spot < 15:
                gex_lines.append(
                    f"  VIX {fmt(vix_spot)} → Likely POSITIVE GEX environment. "
                    "Expect mean-reversion, 15–30 pt daily range."
                )
            elif vix_spot < 20:
                gex_lines.append(
                    f"  VIX {fmt(vix_spot)} → Mixed GEX environment. "
                    "Normal ranges, no strong dealer hedging signal."
                )
            elif vix_spot < 30:
                gex_lines.append(
                    f"  VIX {fmt(vix_spot)} → Elevated — potential NEGATIVE GEX. "
                    "Expect trending behavior, widen range estimates."
                )
            else:
                gex_lines.append(
                    f"  VIX {fmt(vix_spot)} → Crisis level — almost certainly NEGATIVE GEX. "
                    "Dealer hedging AMPLIFIES moves. All bets on trend-following."
                )
        else:
            gex_lines.append("  VIX: N/A — insufficient data for GEX inference.")

    # Expiration calendar context
    expiry_lines = ["=== EXPIRATION CALENDAR ==="]
    if is_opex_week:
        expiry_lines.append(
            "OPEX WEEK: Charm/vanna flows create tailwinds toward expiring strikes. "
            "Market tends to drift toward the largest open interest strike. "
            "Dealer hedging reduces directional volatility — favor mean-reversion."
        )
    elif is_post_opex:
        expiry_lines.append(
            "POST-OPEX (first 2 sessions): Old gamma dissolved — 'UNCLENCHED' ranges. "
            "Expect ranges to expand 20–30% above normal. Trend days more probable. "
            "Avoid assuming prior mean-reversion dynamics still hold."
        )
    else:
        days_str = f" ({days_to_opex}d to OPEX)" if days_to_opex is not None else ""
        expiry_lines.append(f"Normal calendar week{days_str}. Standard dealer hedging patterns.")

    # 0DTE context
    dte_lines: list[str] = []
    if minutes_to_close is not None and minutes_to_close <= 90:
        dte_lines = [
            "",
            "=== 0DTE AMPLIFICATION WINDOW ===",
            f"⚠ {minutes_to_close} minutes to RTH close — 0DTE options at extreme gamma.",
            "SPX 0DTE = ~59% of total SPX options volume. ATM gamma spikes near expiry.",
            "Episodic one-sided 0DTE flow creates amplification events near strikes.",
            "Strike battles intensify — watch for rapid reversals at round strike levels.",
            (
                "At 3:50 PM: NYSE MOC imbalance published — drives final directional push. "
                "Institutional agent has priority on this signal."
            ),
        ]

    lines = [
        f"=== MARKET MAKER AGENT — {config['name']} ===",
        "ROLE: You are a DELTA-HEDGING DEALER, not a speculator.",
        "Your behavior is mechanically DETERMINED by GEX regime sign — not personal opinion.",
        "Positive GEX = you buy dips/sell rallies (mean-revert). "
        "Negative GEX = you sell dips/buy rallies (amplify). THIS IS YOUR RULE.",
        "",
        "=== MARKET INTERNALS (Your Exclusive Signal) ===",
        f"NYSE TICK: {tick_signal}",
        f"NYSE ADD (Advance-Decline): {add_signal}",
        f"NYSE VOLD (Up Vol - Down Vol): {vold_signal}",
        "",
        f"VIX: {fmt(vix_spot)} (implied vol reference for hedging calculations)",
        f"{config['name']} Price: {fmt(es_price)}",
        "",
        *gex_lines,
        "",
        *expiry_lines,
        *dte_lines,
        "",
        "=== HEDGING RULES ===",
        "Positive GEX: First target = nearest GEX wall. Tighten stops.",
        "Negative GEX: Trend-follow. Targets extend 20% beyond Put/Call Wall levels.",
        "Vanna/Charm (OPEX): After-vol-crush events → mechanical vanna rallies expected.",
        "After benign macro (FOMC hold, in-line CPI): IV crush → vanna flows support rallies.",
    ]
    if nyse_tick is None and nyse_add is None:
        lines.append("")
        lines.append(
            "NOTE: Market internals offline (IB relay not configured). "
            "Rely on VIX, GEX regime, and price action for flow inference."
        )

    return "\n".join(lines)

"""Institutional agent context block template.

Role: VWAP-benchmarking institutional algorithm operator. Think in terms of
VWAP benchmarking, liquidity absorption, execution algorithm footprints, and
key level hierarchy — not speculation or technical pattern prediction.

Supplementary data exclusive to this agent (not shared with retail or market maker):
- Session key levels: VWAP, PDH/PDL, ONH/ONL, IB H/L, round numbers
- Order flow context: VWAP absorption patterns
- Event-day protocols: FOMC four-stage pattern, MOC imbalance timing
"""

from mirofish_forecast.config.constants import get_instrument_config


def build_institutional_context_template(
    instrument: str = "ES",
    fed_funds: float | None = None,
    ten_year: float | None = None,
    two_year: float | None = None,
    spread_2s10s: float | None = None,
    cpi_yoy: float | None = None,
    gdp_growth: float | None = None,
    unemployment: float | None = None,
    vix_spot: float | None = None,
    vix_regime: str | None = None,
    fear_greed: float | None = None,
    es_price: float | None = None,
    dxy_price: float | None = None,
    tlt_price: float | None = None,
    gld_price: float | None = None,
    crude_price: float | None = None,
    # Session key levels (from Databento / session_levels.py)
    session_vwap: float | None = None,
    session_vwap_upper: float | None = None,
    session_vwap_lower: float | None = None,
    prior_rth_high: float | None = None,
    prior_rth_low: float | None = None,
    prior_rth_close: float | None = None,
    overnight_high: float | None = None,
    overnight_low: float | None = None,
    ib_high: float | None = None,
    ib_low: float | None = None,
    ib_range: float | None = None,
    today_rth_open: float | None = None,
    # MOC context
    moc_imbalance_usd: float | None = None,  # $ value of MOC imbalance (positive = buy)
    minutes_to_moc: int | None = None,  # Minutes until 3:50 PM MOC data release
) -> str:
    """Build a deterministic institutional context block from raw values."""
    config = get_instrument_config(instrument)

    def fmt(val: float | None, suffix: str = "", decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}{suffix}"

    def fmtb(val: float | None, decimals: int = 2) -> str:
        """Format a dollar value in billions."""
        if val is None:
            return "N/A"
        return f"${val / 1e9:.1f}B"

    # Yield curve interpretation
    curve_signal = "N/A"
    if spread_2s10s is not None:
        if spread_2s10s < 0:
            curve_signal = f"INVERTED ({fmt(spread_2s10s)}%) — recession signal, risk-off"
        elif spread_2s10s < 0.25:
            curve_signal = f"FLAT ({fmt(spread_2s10s)}%) — late cycle, caution"
        elif spread_2s10s < 1.0:
            curve_signal = f"MILDLY STEEP ({fmt(spread_2s10s)}%) — normal, mild growth expectations"
        else:
            curve_signal = f"STEEP ({fmt(spread_2s10s)}%) — growth expectations, risk-on"

    # VWAP absorption signal
    vwap_ctx = "VWAP: N/A"
    if session_vwap is not None and es_price is not None:
        dist = es_price - session_vwap
        side = "ABOVE" if dist >= 0 else "BELOW"
        vwap_ctx = f"VWAP: {fmt(session_vwap)} | Price {side} by {abs(dist):.2f} pts"
        if session_vwap_upper and session_vwap_lower:
            vwap_ctx += f" | Bands: {fmt(session_vwap_lower)} – {fmt(session_vwap_upper)}"
        # Absorption signal: price near VWAP = mean-revert pressure
        if abs(dist) < 2.0:
            vwap_ctx += " ← AT VWAP: institutional buying/selling expected here"
        elif abs(dist) > 15.0 and side == "ABOVE":
            vwap_ctx += " ← EXTENDED ABOVE VWAP: mean-reversion risk elevated"
        elif abs(dist) > 15.0 and side == "BELOW":
            vwap_ctx += " ← EXTENDED BELOW VWAP: potential snap-back to VWAP"

    # Key level hierarchy (priority order per Brooks/institutional framework)
    level_lines = ["KEY LEVEL HIERARCHY (highest priority first):"]

    # 1. VWAP (primary institutional benchmark — 72% of volume is VWAP-benchmarked)
    level_lines.append(f"  1. {vwap_ctx}")

    # 2. Prior Day RTH High/Low
    if prior_rth_high is not None:
        level_lines.append(
            f"  2. Prior Day RTH: H={fmt(prior_rth_high)}, L={fmt(prior_rth_low)}, "
            f"C={fmt(prior_rth_close)} "
            f"(PDH break → ~67% close above PDH)"
        )
    else:
        level_lines.append("  2. Prior Day RTH: N/A")

    # 3. Overnight High/Low
    if overnight_high is not None:
        level_lines.append(
            f"  3. Overnight Range: H={fmt(overnight_high)}, L={fmt(overnight_low)} "
            f"(international flow boundary)"
        )
    else:
        level_lines.append("  3. Overnight Range: N/A")

    # 4. Initial Balance High/Low
    if ib_high is not None:
        level_lines.append(
            f"  4. Initial Balance: H={fmt(ib_high)}, L={fmt(ib_low)}, "
            f"Range={fmt(ib_range)} pts "
            f"(97.8% of days break ≥1 IB extreme; single-direction break = 68–77% continuation)"
        )
    else:
        level_lines.append("  4. Initial Balance: Not yet formed (< 60 min RTH)")

    # 5. Today's RTH Open
    if today_rth_open is not None:
        level_lines.append(f"  5. Today RTH Open: {fmt(today_rth_open)}")

    # 6. Round numbers
    if es_price is not None:
        round_spacing = {"ES": 50, "NQ": 250, "CL": 1.0, "GC": 25}.get(instrument.upper(), 50)
        lower_round = int(es_price / round_spacing) * round_spacing
        upper_round = lower_round + round_spacing
        level_lines.append(
            f"  6. Round Numbers: {lower_round} (support) / {upper_round} (resistance)"
            f" — institutional stop-hunt and liquidity target zones"
        )

    # MOC imbalance context
    moc_lines = []
    if moc_imbalance_usd is not None:
        direction_str = "BUY" if moc_imbalance_usd > 0 else "SELL"
        abs_usd = abs(moc_imbalance_usd)
        significance = "SIGNIFICANT (>$1B imbalance)" if abs_usd > 1e9 else "moderate"
        moc_lines = [
            "",
            "=== MOC IMBALANCE (3:50 PM Data) ===",
            f"NYSE MOC Imbalance: {direction_str} {fmtb(abs_usd)} — {significance}",
            (
                "RULE: $1B+ imbalances shift closing price ~5.5 bps average. "
                "Weight this heavily in final-hour directional call."
                if abs_usd > 1e9
                else "Imbalance below $1B threshold — limited final-hour impact expected."
            ),
        ]
    elif minutes_to_moc is not None and minutes_to_moc <= 15:
        moc_lines = [
            "",
            f"=== MOC Data Due in {minutes_to_moc} minutes (3:50 PM) ===",
            "NYSE MOC imbalance data imminent — avoid large directional commitments until released.",
        ]

    lines = [
        f"=== INSTITUTIONAL AGENT — {config['name']} ===",
        "ROLE: You are a VWAP-benchmarking institutional execution algorithm.",
        "You think in terms of: VWAP advantage/disadvantage, liquidity absorption at key levels,",
        "U-shaped volume curve positioning, and order flow imbalance — NOT speculation.",
        "72% of institutional volume is VWAP-executed. Your risk is tracking error vs VWAP.",
        "",
        "=== MACRO CONTEXT ===",
        f"Fed Funds Rate: {fmt(fed_funds, '%')}",
        f"10Y Yield: {fmt(ten_year, '%')} | 2Y Yield: {fmt(two_year, '%')}",
        f"2s10s Spread: {curve_signal}",
        f"CPI YoY: {fmt(cpi_yoy, '%')} | GDP Growth: {fmt(gdp_growth, '%')} | Unemployment: {fmt(unemployment, '%')}",
        f"VIX: {fmt(vix_spot)} ({(vix_regime or 'unknown').upper()})",
        f"Fear & Greed: {fmt(fear_greed, '', 0)}",
        "",
        "=== CROSS-ASSET SIGNALS ===",
        f"DXY: {fmt(dxy_price)} | TLT (Bonds): {fmt(tlt_price)} | Gold: {fmt(gld_price)} | Crude: {fmt(crude_price)}",
        f"{instrument.upper()} Current: {fmt(es_price)}",
        "",
        *level_lines,
        *moc_lines,
        "",
        "=== EXECUTION ALGORITHM CONTEXT ===",
        "Absorption signal: Narrow-range bars + volume ≥ 1.3× average at key level = accumulation.",
        "FOMC days: pre-announcement range 30–50% of normal; initial spike reverses 60–70% by close.",
        "VWAP recoil: After strong trends, first pullback to 20-EMA in trend direction is high-prob entry.",
        "MOC flow (~7% of daily volume): $1B+ imbalances drive closing push with high reliability.",
    ]
    return "\n".join(lines)

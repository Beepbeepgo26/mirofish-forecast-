"""Retail agent context block template.

Role: Contrarian sentiment analyst. Identifies when crowd behavior creates
exploitable inefficiencies. Core premise: retail traders exhibit the disposition
effect (4× more likely to sell winners), chase breakouts that fail 35–45% of
the time, and cluster stops at obvious levels that institutions systematically sweep.

Supplementary data exclusive to this agent (not shared with institutional or market maker):
- CBOE equity put/call ratio
- AAII bearish sentiment percentage
- Gap from prior close (gap fade probability)
- Fear & Greed extremes for contrarian signals
"""

from mirofish_forecast.config.constants import get_instrument_config


def build_retail_context_template(
    instrument: str = "ES",
    fear_greed: float | None = None,
    fear_greed_desc: str | None = None,
    vix_spot: float | None = None,
    es_price: float | None = None,
    nq_price: float | None = None,
    spy_price: float | None = None,
    # Exclusive retail-contrarian data
    put_call_ratio: float
    | None = None,  # CBOE Equity Put/Call (>1.2=extreme bearish; <0.7=extreme bullish)
    aaii_bearish_pct: float | None = None,  # AAII % bearish (>50% = bottom signal)
    gap_from_prior_close: float | None = None,  # ES points gap at open vs prior RTH close
    prior_rth_close: float | None = None,  # For gap fill probability context
    current_price_for_gap: float | None = None,  # Current price to compute gap fill progress
) -> str:
    """Build a deterministic retail contrarian context block from raw values."""
    config = get_instrument_config(instrument)

    def fmt(val: float | None, decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}"

    # Fear & Greed interpretation with contrarian thresholds
    fg_reading = "N/A"
    fg_contrarian = ""
    if fear_greed is not None:
        if fear_greed < 20:
            fg_reading = f"{fear_greed:.0f} — EXTREME FEAR"
            fg_contrarian = (
                "⚠ CONTRARIAN BUY SIGNAL: Extreme fear historically precedes bounces. "
                "AAII 70.3% bearish marked the March 2009 bottom. "
                "61.9% bearish in April 2025 preceded a strong rally."
            )
        elif fear_greed < 40:
            fg_reading = f"{fear_greed:.0f} — FEAR"
            fg_contrarian = (
                "Mild contrarian lean toward longs. Crowd is nervous — potential bounce fuel."
            )
        elif fear_greed < 60:
            fg_reading = f"{fear_greed:.0f} — NEUTRAL"
            fg_contrarian = "No strong contrarian signal. Crowd is balanced."
        elif fear_greed < 80:
            fg_reading = f"{fear_greed:.0f} — GREED"
            fg_contrarian = "Mild contrarian lean toward shorts. Complacency risk building."
        else:
            fg_reading = f"{fear_greed:.0f} — EXTREME GREED"
            fg_contrarian = (
                "⚠ CONTRARIAN SELL SIGNAL: Extreme greed historically precedes pullbacks. "
                "Crowd is overly confident — smart money distributes into retail euphoria."
            )

    # VIX contrarian gauge
    vix_signal = "N/A"
    if vix_spot is not None:
        if vix_spot > 50:
            vix_signal = (
                f"{vix_spot:.1f} — CAPITULATION TERRITORY: "
                "VIX > 50 historically marks panic bottoms. Strong contrarian buy signal."
            )
        elif vix_spot > 40:
            vix_signal = (
                f"{vix_spot:.1f} — CRISIS LEVEL: "
                "Fear spike often exceeds fundamental risk. Watch for VIX reversal as buy signal."
            )
        elif vix_spot > 30:
            vix_signal = f"{vix_spot:.1f} — Elevated fear, potential contrarian buy on dips."
        elif vix_spot < 15:
            vix_signal = (
                f"{vix_spot:.1f} — COMPLACENCY LEVEL: "
                "VIX < 15 = market underpricing risk. Contrarian signal toward caution."
            )
        else:
            vix_signal = f"{vix_spot:.1f} — Normal range, no extreme contrarian signal."

    # Put/Call ratio interpretation
    pcr_lines = []
    if put_call_ratio is not None:
        if put_call_ratio > 1.2:
            pcr_lines = [
                f"CBOE Put/Call Ratio: {put_call_ratio:.2f} — EXTREME BEARISH (>1.2)",
                "⚠ CONTRARIAN BUY: Crowd is heavily positioned in puts. "
                "Historically, extreme put/call marks short-term bottoms.",
            ]
        elif put_call_ratio > 0.9:
            pcr_lines = [
                f"CBOE Put/Call Ratio: {put_call_ratio:.2f} — Bearish lean, mild contrarian buy"
            ]
        elif put_call_ratio < 0.7:
            pcr_lines = [
                f"CBOE Put/Call Ratio: {put_call_ratio:.2f} — EXTREME BULLISH (<0.7)",
                "⚠ CONTRARIAN SELL: Crowd is heavily positioned in calls. "
                "Market may be priced for perfection — vulnerable to disappointment.",
            ]
        else:
            pcr_lines = [f"CBOE Put/Call Ratio: {put_call_ratio:.2f} — Neutral range"]
    else:
        pcr_lines = ["CBOE Put/Call Ratio: N/A"]

    # AAII sentiment
    aaii_lines = []
    if aaii_bearish_pct is not None:
        if aaii_bearish_pct > 50:
            aaii_lines = [
                f"AAII Bearish Sentiment: {aaii_bearish_pct:.1f}% bearish",
                "⚠ STRONG CONTRARIAN BUY: >50% bearish historically marks bottoms. "
                "(70.3% bearish = March 2009 exact bottom; 61.9% = April 2025 rally launch)",
            ]
        elif aaii_bearish_pct > 40:
            aaii_lines = [
                f"AAII Bearish Sentiment: {aaii_bearish_pct:.1f}% — Elevated, mild contrarian lean"
            ]
        else:
            aaii_lines = [f"AAII Bearish Sentiment: {aaii_bearish_pct:.1f}% — Normal range"]
    else:
        aaii_lines = ["AAII Bearish Sentiment: N/A"]

    # Gap fade analysis
    gap_lines = []
    if gap_from_prior_close is not None and prior_rth_close is not None:
        abs_gap = abs(gap_from_prior_close)
        gap_dir = "UP" if gap_from_prior_close > 0 else "DOWN"
        if abs_gap < 5:
            fill_prob = "~78%"
            fill_note = "Small gap: very high fill probability within 30 min."
        elif abs_gap < 10:
            fill_prob = "~70%"
            fill_note = "Medium gap: high fill probability, often within 60 min."
        elif abs_gap < 20:
            fill_prob = "~55%"
            fill_note = "Large gap: moderate fill probability. Wait for reversal confirmation."
        elif abs_gap < 30:
            fill_prob = "~30%"
            fill_note = "Very large gap: low fill probability. Likely a continuation day."
        else:
            fill_prob = "~8%"
            fill_note = "Extreme gap: rarely fills same day. Follow gap momentum instead."

        fill_target = fmt(prior_rth_close)

        # Gap fill progress
        if current_price_for_gap is not None and abs_gap > 0:
            remaining = abs(current_price_for_gap - prior_rth_close)
            pct_filled = max(0, min(100, (1 - remaining / abs_gap) * 100))
            progress_str = f" | Fill progress: {pct_filled:.0f}%"
        else:
            progress_str = ""

        gap_lines = [
            "",
            "=== GAP ANALYSIS (Retail Contrarian Signal) ===",
            f"Overnight Gap: {gap_dir} {abs_gap:.1f} pts from prior RTH close ({fill_target})",
            f"Gap Fill Probability: {fill_prob}{progress_str}",
            fill_note,
            "Rule: 40.6% of ES fills complete within first 15 min; 50%+ within 30 min.",
            (
                "CONTRARIAN LEAN: "
                + (
                    "Fade this down gap if < 10 pts — gap fill toward " + fill_target + " likely."
                    if gap_dir == "DOWN" and abs_gap < 10
                    else "Fade this up gap if < 10 pts — gap fill toward "
                    + fill_target
                    + " likely."
                    if gap_dir == "UP" and abs_gap < 10
                    else "Large gap — do NOT fade. Follow gap direction."
                )
            ),
        ]

    # Round number levels
    round_levels = ""
    if es_price is not None:
        round_spacing = {"ES": 50, "NQ": 250, "CL": 1.0, "GC": 25}.get(instrument.upper(), 50)
        lower_round = int(es_price / round_spacing) * round_spacing
        upper_round = lower_round + round_spacing
        round_levels = (
            f"Key round numbers: {lower_round} / {upper_round} "
            f"— retail clusters stops here, institutions run them"
        )

    lines = [
        f"=== RETAIL CONTRARIAN AGENT — {config['name']} ===",
        "ROLE: You are a CONTRARIAN SENTIMENT ANALYST, not a trend follower.",
        "Your edge: retail traders are predictably wrong at extremes.",
        "Core biases to exploit: Disposition effect (4× more likely to sell winners),",
        "breakout-chasing (fails 35–45% of the time), and stop clustering at obvious levels.",
        "",
        "=== SENTIMENT INDICATORS (Your Exclusive Signal) ===",
        f"Fear & Greed Index: {fg_reading}",
        fg_contrarian,
        f"VIX Contrarian Signal: {vix_signal}",
        "",
        *pcr_lines,
        *aaii_lines,
        "",
        "=== SENTIMENT THRESHOLD TABLE ===",
        "Indicator        | Extreme Bearish (Contrarian BUY) | Extreme Bullish (Contrarian SELL)",
        "CBOE Equity P/C  | > 1.2                            | < 0.7",
        "VIX              | > 40 (crisis); > 50 (capitulation) | < 15 (complacency)",
        "AAII Bearish     | > 50%                            | Bullish > 55% (weak signal)",
        "Fear & Greed     | < 20 (extreme fear)              | > 80 (extreme greed)",
        "",
        "=== STOP-HUNT RECOGNITION PROTOCOL ===",
        "Pattern: Price breaks obvious support/resistance by small margin → rejection wick",
        "+ volume spike → reversal within 1–3 bars = LIQUIDITY SWEEP by institutions.",
        "Action: FLAG this pattern, REVERSE directional bias.",
        "Rule: Higher-timeframe levels carry more weight (daily > hourly > 5-min).",
        "Brooks term: 'Trapped traders' — their forced exits fuel the institutional move.",
        *gap_lines,
        "",
        "=== PRICE CONTEXT ===",
        f"{config['name']}: {fmt(es_price)}",
        f"NQ Futures: {fmt(nq_price)}",
        f"SPY: {fmt(spy_price)}",
        round_levels,
    ]
    return "\n".join(lines)

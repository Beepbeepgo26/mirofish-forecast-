"""Retail agent context block template — sentiment-first, simple language."""


def build_retail_context_template(
    fear_greed: float | None,
    fear_greed_desc: str | None,
    vix_spot: float | None,
    es_price: float | None,
    nq_price: float | None,
    spy_price: float | None,
) -> str:
    """Build a deterministic retail context block from raw values."""

    def fmt(val: float | None, decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}"

    # Fear & Greed interpretation
    fg_reading = "N/A"
    if fear_greed is not None:
        if fear_greed < 20:
            fg_reading = (
                f"{fear_greed:.0f} — EXTREME FEAR (historically, markets often bounce from here)"
            )
        elif fear_greed < 40:
            fg_reading = (
                f"{fear_greed:.0f} — FEAR"
                " (crowd is nervous, contrarian signal for potential bounce)"
            )
        elif fear_greed < 60:
            fg_reading = f"{fear_greed:.0f} — NEUTRAL (no strong signal either way)"
        elif fear_greed < 80:
            fg_reading = f"{fear_greed:.0f} — GREED (crowd is confident, potential complacency)"
        else:
            fg_reading = (
                f"{fear_greed:.0f} — EXTREME GREED (historically, pullbacks often start from here)"
            )

    # VIX simple gauge
    vix_gauge = "N/A"
    if vix_spot is not None:
        if vix_spot < 15:
            vix_gauge = f"{vix_spot:.1f} — Markets are calm, low volatility expected"
        elif vix_spot < 20:
            vix_gauge = f"{vix_spot:.1f} — Normal conditions"
        elif vix_spot < 25:
            vix_gauge = f"{vix_spot:.1f} — Markets are getting nervous"
        elif vix_spot < 30:
            vix_gauge = f"{vix_spot:.1f} — Elevated fear, expect bigger swings"
        else:
            vix_gauge = f"{vix_spot:.1f} — HIGH FEAR, markets are stressed"

    # Round number levels
    round_levels = ""
    if es_price is not None:
        lower_round = int(es_price / 50) * 50
        upper_round = lower_round + 50
        round_levels = f"Key round numbers: {lower_round}, {upper_round}"

    lines = [
        "=== SENTIMENT & PRICE CONTEXT ===",
        f"Fear & Greed Index: {fg_reading}",
        f"VIX (Fear Gauge): {vix_gauge}",
        "",
        f"ES Futures: {fmt(es_price)}",
        f"NQ Futures: {fmt(nq_price)}",
        f"SPY: {fmt(spy_price)}",
        round_levels,
    ]
    return "\n".join(lines)

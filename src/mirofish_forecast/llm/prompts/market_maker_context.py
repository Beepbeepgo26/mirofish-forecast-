"""Market maker agent context block template — positioning and flow first."""


def build_market_maker_context_template(
    nyse_tick: float | None,
    nyse_add: float | None,
    nyse_vold: float | None,
    vix_spot: float | None,
    es_price: float | None,
) -> str:
    """Build a deterministic market maker context block from raw values."""

    def fmt(val: float | None, decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}"

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

    lines = [
        "=== FLOW & POSITIONING CONTEXT ===",
        f"NYSE TICK: {tick_signal}",
        f"NYSE ADD (Advance-Decline): {add_signal}",
        f"NYSE VOLD (Up Vol - Down Vol): {vold_signal}",
        "",
        f"VIX: {fmt(vix_spot)} (implied vol reference for hedging calculations)",
        f"ES Price: {fmt(es_price)}",
        "",
        "NOTE: If TICK, ADD, and VOLD are all N/A, IB market internals relay is offline.",
        "In this case, rely on VIX and price action for flow inference.",
    ]
    return "\n".join(lines)

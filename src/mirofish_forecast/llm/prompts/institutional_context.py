"""Institutional agent context block template.

Used as a fallback when the LLM interpret_context call fails.
Provides a deterministic template-fill approach.
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
) -> str:
    """Build a deterministic institutional context block from raw values."""
    config = get_instrument_config(instrument)

    def fmt(val: float | None, suffix: str = "", decimals: int = 2) -> str:
        if val is None:
            return "N/A"
        return f"{val:.{decimals}f}{suffix}"

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

    lines = [
        f"=== MACRO & POSITIONING CONTEXT ({config['name']}) ===",
        f"Product: {config['description']}",
        f"Key Drivers: {config['key_drivers']}",
        "",
        f"Fed Funds Rate: {fmt(fed_funds, '%')}",
        f"10Y Yield: {fmt(ten_year, '%')} | 2Y Yield: {fmt(two_year, '%')}",
        f"2s10s Spread: {curve_signal}",
        (
            f"CPI YoY: {fmt(cpi_yoy, '%')} | GDP Growth: {fmt(gdp_growth, '%')}"
            f" | Unemployment: {fmt(unemployment, '%')}"
        ),
        f"VIX: {fmt(vix_spot)} ({(vix_regime or 'unknown').upper()})",
        f"Fear & Greed: {fmt(fear_greed, '', 0)}",
        "",
        "=== CROSS-ASSET SIGNALS ===",
        (
            f"DXY: {fmt(dxy_price)} | TLT (Bonds): {fmt(tlt_price)}"
            f" | Gold: {fmt(gld_price)} | Crude: {fmt(crude_price)}"
        ),
        "",
        f"=== {instrument.upper()} CURRENT PRICE: {fmt(es_price)} ===",
    ]
    return "\n".join(lines)

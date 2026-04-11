"""Test multi-instrument configuration and price resolution."""

from mirofish_forecast.config.constants import (
    INSTRUMENT_CONFIG,
    get_instrument_config,
)


class TestInstrumentConfig:
    def test_all_instruments_have_required_fields(self) -> None:
        required = [
            "name",
            "yfinance_ticker",
            "asset_class",
            "tick_size",
            "point_value",
            "typical_daily_range",
            "max_bar_move_pct",
            "drift_anchor_weight",
            "price_decimals",
            "description",
            "key_drivers",
        ]
        for symbol, config in INSTRUMENT_CONFIG.items():
            for field in required:
                assert field in config, f"{symbol} missing field: {field}"

    def test_es_config(self) -> None:
        config = get_instrument_config("ES")
        assert config["yfinance_ticker"] == "ES=F"
        assert config["max_bar_move_pct"] == 0.0015

    def test_nq_config(self) -> None:
        config = get_instrument_config("NQ")
        assert config["yfinance_ticker"] == "NQ=F"
        assert config["max_bar_move_pct"] > get_instrument_config("ES")["max_bar_move_pct"]

    def test_cl_config(self) -> None:
        config = get_instrument_config("CL")
        assert config["asset_class"] == "commodity_energy"
        assert config["point_value"] == 1000.0

    def test_gc_config(self) -> None:
        config = get_instrument_config("GC")
        assert config["asset_class"] == "commodity_metal"

    def test_unknown_defaults_to_es(self) -> None:
        config = get_instrument_config("FAKE")
        assert config["name"] == "E-mini S&P 500"

    def test_case_insensitive(self) -> None:
        assert get_instrument_config("es") == get_instrument_config("ES")

    def test_volatility_ordering(self) -> None:
        """CL should have wider bars than ES (more volatile)."""
        es = get_instrument_config("ES")
        cl = get_instrument_config("CL")
        assert cl["max_bar_move_pct"] > es["max_bar_move_pct"]


class TestPriceGuidance:
    def test_es_guidance(self) -> None:
        from mirofish_forecast.services.simulation_runner import MonteCarloRunner

        guidance = MonteCarloRunner._get_price_guidance("ES", 5420.0)
        assert "10 points" in guidance
        assert "$50" in guidance

    def test_cl_guidance(self) -> None:
        from mirofish_forecast.services.simulation_runner import MonteCarloRunner

        guidance = MonteCarloRunner._get_price_guidance("CL", 78.50)
        assert "$0.50" in guidance
        assert "$1,000" in guidance

    def test_gc_guidance(self) -> None:
        from mirofish_forecast.services.simulation_runner import MonteCarloRunner

        guidance = MonteCarloRunner._get_price_guidance("GC", 2350.0)
        assert "$15" in guidance
        assert "$100" in guidance

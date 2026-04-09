"""Test FRED client — macro indicators fetch."""

from unittest.mock import patch

import pandas as pd

from mirofish_forecast.data.fred_client import FredClient


class TestFredClient:
    def test_returns_macro_indicators_on_success(self, mock_settings, mock_cache):
        with patch("mirofish_forecast.data.fred_client.Fred") as mock_fred_cls:
            mock_fred_instance = mock_fred_cls.return_value
            mock_fred_instance.get_series.return_value = pd.Series([5.25, 5.33])

            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            assert result.fed_funds_rate == 5.33
            assert result.as_of is not None
            mock_cache.set.assert_called_once()

    def test_returns_partial_on_api_error(self, mock_settings, mock_cache):
        with patch("mirofish_forecast.data.fred_client.Fred") as mock_fred_cls:
            mock_fred_instance = mock_fred_cls.return_value
            mock_fred_instance.get_series.side_effect = Exception("API error")

            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            assert result.fed_funds_rate is None
            assert result.as_of is not None

    def test_returns_cached_data(self, mock_settings, mock_cache):
        cached_json = (
            '{"fed_funds_rate": 5.25, "cpi_yoy": 2.8,'
            ' "gdp_growth": 2.4, "as_of": "2025-01-01T00:00:00"}'
        )
        mock_cache.get.return_value = cached_json

        with patch("mirofish_forecast.data.fred_client.Fred"):
            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            assert result.fed_funds_rate == 5.25
            assert result.cpi_yoy == 2.8
            assert result.gdp_growth == 2.4

    def test_cpi_yoy_fallback_calculation(self, mock_settings, mock_cache):
        """If the OECD CPI YoY series fails, compute from raw CPI index."""
        with patch("mirofish_forecast.data.fred_client.Fred") as mock_fred_cls:
            mock_fred_instance = mock_fred_cls.return_value

            def mock_get_series(series_id, **kwargs):
                if series_id == "CPALTT01USM657N":
                    raise Exception("Series not available")
                if series_id == "CPIAUCSL":
                    return pd.Series([310.0 + i * 0.6 for i in range(14)])
                return pd.Series([4.5])

            mock_fred_instance.get_series.side_effect = mock_get_series

            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            assert result.cpi_yoy is not None
            assert isinstance(result.cpi_yoy, float)

    def test_gdp_growth_is_percentage(self, mock_settings, mock_cache):
        """GDP growth should be a small percentage, not billions of dollars."""
        with patch("mirofish_forecast.data.fred_client.Fred") as mock_fred_cls:
            mock_fred_instance = mock_fred_cls.return_value
            mock_fred_instance.get_series.return_value = pd.Series([2.8, 3.1, 2.4])

            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            if result.gdp_growth is not None:
                assert -10.0 < result.gdp_growth < 20.0, (
                    f"GDP growth {result.gdp_growth} looks like raw GDP, not growth rate"
                )

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

            assert result.fed_funds_rate == 5.33  # Latest value
            assert result.as_of is not None
            mock_cache.set.assert_called_once()

    def test_returns_partial_on_api_error(self, mock_settings, mock_cache):
        with patch("mirofish_forecast.data.fred_client.Fred") as mock_fred_cls:
            mock_fred_instance = mock_fred_cls.return_value
            mock_fred_instance.get_series.side_effect = Exception("API error")

            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            # Should return a model with None fields, not crash
            assert result.fed_funds_rate is None
            assert result.as_of is not None

    def test_returns_cached_data(self, mock_settings, mock_cache):
        cached_json = '{"fed_funds_rate": 5.25, "as_of": "2025-01-01T00:00:00"}'
        mock_cache.get.return_value = cached_json

        with patch("mirofish_forecast.data.fred_client.Fred"):
            client = FredClient(mock_settings, mock_cache)
            result = client.get_macro_indicators()

            assert result.fed_funds_rate == 5.25

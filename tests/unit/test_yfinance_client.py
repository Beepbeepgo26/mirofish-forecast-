from unittest.mock import patch

from mirofish_forecast.data.yfinance_client import YFinanceClient


class TestYFinanceClient:
    def test_returns_snapshot_on_success(self, mock_cache):
        with patch("mirofish_forecast.data.yfinance_client.yf") as mock_yf:
            import pandas as pd

            # Create mock multi-level columns DataFrame
            arrays = [["Close"] * 2, ["ES=F", "SPY"]]
            tuples = list(zip(*arrays))
            index = pd.MultiIndex.from_tuples(tuples)
            df = pd.DataFrame([[5420.0, 540.0]], columns=index)

            mock_yf.download.return_value = df

            client = YFinanceClient(mock_cache)
            result = client.get_cross_asset_snapshot()

            assert result.es_price == 5420.0
            assert result.spy_price == 540.0
            assert result.as_of is not None

    def test_returns_empty_on_error(self, mock_cache):
        with patch("mirofish_forecast.data.yfinance_client.yf") as mock_yf:
            mock_yf.download.side_effect = Exception("Network error")

            client = YFinanceClient(mock_cache)
            result = client.get_cross_asset_snapshot()

            assert result.es_price is None
            assert result.as_of is not None

    def test_returns_cached_data(self, mock_cache):
        cached_json = '{"es_price": 5420.0, "spy_price": 540.0}'
        mock_cache.get.return_value = cached_json

        client = YFinanceClient(mock_cache)
        result = client.get_cross_asset_snapshot()

        assert result.es_price == 5420.0
        assert result.spy_price == 540.0

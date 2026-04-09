from unittest.mock import MagicMock, patch

from mirofish_forecast.data.ib_client import IBClient


class TestIBClient:
    def test_returns_internals_on_success(self, mock_settings, mock_cache):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"value": -200.0}
        mock_response.raise_for_status.return_value = None

        with patch("mirofish_forecast.data.ib_client.requests.get", return_value=mock_response):
            client = IBClient(mock_settings, mock_cache)
            result = client.get_market_internals()

            assert result.nyse_tick == -200.0
            assert result.nyse_add == -200.0
            assert result.nyse_vold == -200.0

    def test_returns_partial_on_relay_down(self, mock_settings, mock_cache):
        with patch(
            "mirofish_forecast.data.ib_client.requests.get",
            side_effect=Exception("Connection refused"),
        ):
            client = IBClient(mock_settings, mock_cache)
            result = client.get_market_internals()

            assert result.nyse_tick is None
            assert result.as_of is not None

from unittest.mock import MagicMock, patch

from mirofish_forecast.data.fear_greed_client import FearGreedClient


class TestFearGreedClient:
    def test_returns_data_on_success(self, mock_cache):
        with patch("mirofish_forecast.data.fear_greed_client.fear_and_greed") as mock_fg:
            mock_result = MagicMock()
            mock_result.value = 38.0
            mock_result.description = "Fear"
            mock_fg.get.return_value = mock_result

            client = FearGreedClient(mock_cache)
            result = client.get_fear_greed()

            assert result.value == 38.0
            assert result.description == "Fear"

    def test_returns_empty_on_error(self, mock_cache):
        with patch("mirofish_forecast.data.fear_greed_client.fear_and_greed") as mock_fg:
            mock_fg.get.side_effect = Exception("Network error")

            client = FearGreedClient(mock_cache)
            result = client.get_fear_greed()

            assert result.value is None

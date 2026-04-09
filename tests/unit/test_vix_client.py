from unittest.mock import patch

from mirofish_forecast.data.vix_client import (
    VixClient,
    _classify_term_structure,
    _classify_vix_regime,
)
from mirofish_forecast.models.market import VIXRegime, VIXTermStructure


class TestVixRegimeClassification:
    def test_complacent(self):
        assert _classify_vix_regime(12.0) == VIXRegime.COMPLACENT

    def test_normal(self):
        assert _classify_vix_regime(17.0) == VIXRegime.NORMAL

    def test_elevated(self):
        assert _classify_vix_regime(25.0) == VIXRegime.ELEVATED

    def test_fear(self):
        assert _classify_vix_regime(35.0) == VIXRegime.FEAR


class TestTermStructureClassification:
    def test_contango(self):
        assert _classify_term_structure(20.0, 22.0) == VIXTermStructure.CONTANGO

    def test_backwardation(self):
        assert _classify_term_structure(25.0, 22.0) == VIXTermStructure.BACKWARDATION

    def test_flat(self):
        assert _classify_term_structure(20.0, 20.3) == VIXTermStructure.FLAT


class TestVixClient:
    def test_returns_empty_on_error(self, mock_cache):
        with patch("mirofish_forecast.data.vix_client.vix_utils") as mock_vix:
            mock_vix.download_vix_futures.side_effect = Exception("Network error")

            client = VixClient(mock_cache)
            result = client.get_vix_data()

            assert result.spot is None

    def test_returns_cached_data(self, mock_cache):
        cached_json = '{"spot": 22.5, "regime": "elevated"}'
        mock_cache.get.return_value = cached_json

        client = VixClient(mock_cache)
        result = client.get_vix_data()

        assert result.spot == 22.5
        assert result.regime == VIXRegime.ELEVATED

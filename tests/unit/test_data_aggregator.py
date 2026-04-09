from unittest.mock import patch

from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketInternals,
    VIXData,
)
from mirofish_forecast.services.data_aggregator import DataAggregator


class TestDataAggregator:
    @patch("mirofish_forecast.services.data_aggregator.IBClient")
    @patch("mirofish_forecast.services.data_aggregator.YFinanceClient")
    @patch("mirofish_forecast.services.data_aggregator.FearGreedClient")
    @patch("mirofish_forecast.services.data_aggregator.VixClient")
    @patch("mirofish_forecast.services.data_aggregator.FredClient")
    @patch("mirofish_forecast.services.data_aggregator.CacheClient")
    def test_assembles_market_context(
        self, mock_cache, mock_fred, mock_vix, mock_fg, mock_yf, mock_ib, mock_settings
    ):
        mock_fred.return_value.get_macro_indicators.return_value = MacroIndicators()
        mock_vix.return_value.get_vix_data.return_value = VIXData()
        mock_fg.return_value.get_fear_greed.return_value = FearGreedData()
        mock_yf.return_value.get_cross_asset_snapshot.return_value = CrossAssetSnapshot()
        mock_ib.return_value.get_market_internals.return_value = MarketInternals()

        aggregator = DataAggregator(mock_settings)
        context = aggregator.get_market_context()

        assert context.assembled_at is not None
        assert context.macro is not None
        assert context.vix is not None
        assert context.cross_asset is not None
        assert context.fear_greed is not None
        assert context.internals is not None

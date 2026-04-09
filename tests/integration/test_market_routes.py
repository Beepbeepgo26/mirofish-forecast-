from datetime import datetime
from unittest.mock import patch

from mirofish_forecast.models.market import (
    CrossAssetSnapshot,
    FearGreedData,
    MacroIndicators,
    MarketContext,
    MarketInternals,
    VIXData,
)


class TestMarketRoutes:
    def test_health_startup(self, client):
        resp = client.get("/health/startup")
        assert resp.status_code == 200
        assert resp.json["status"] == "healthy"

    def test_health_liveness(self, client):
        resp = client.get("/health/liveness")
        assert resp.status_code == 200

    @patch("mirofish_forecast.api.market_routes.DataAggregator")
    def test_get_market_context(self, mock_aggregator, client):
        mock_ctx = MarketContext(
            macro=MacroIndicators(fed_funds_rate=5.25),
            vix=VIXData(spot=22.3),
            cross_asset=CrossAssetSnapshot(es_price=5420.0),
            fear_greed=FearGreedData(value=38.0),
            internals=MarketInternals(nyse_tick=-200.0),
            assembled_at=datetime.utcnow(),
        )
        mock_aggregator.return_value.get_market_context.return_value = mock_ctx

        resp = client.get("/api/market/context")
        assert resp.status_code == 200
        data = resp.json
        assert data["macro"]["fed_funds_rate"] == 5.25
        assert data["vix"]["spot"] == 22.3
        assert data["cross_asset"]["es_price"] == 5420.0
        assert data["fear_greed"]["value"] == 38.0
        assert data["internals"]["nyse_tick"] == -200.0

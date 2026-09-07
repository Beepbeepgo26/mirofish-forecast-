"""Integration tests for the forecast API endpoints."""

from unittest.mock import patch

import pytest

from mirofish_forecast.models.market import CrossAssetSnapshot

_AGGREGATOR = "mirofish_forecast.api.forecast_routes.DataAggregator"
_PIPELINE = "mirofish_forecast.api.forecast_routes.ForecastPipeline"


@pytest.fixture
def live_price():
    """Make the /start pre-flight see a live ES price."""
    with patch(_AGGREGATOR) as aggregator_cls:
        aggregator_cls.return_value.get_cross_asset_snapshot.return_value = CrossAssetSnapshot(
            es_price=5420.0
        )
        yield aggregator_cls


class TestForecastStart:
    def test_start_returns_forecast_id(self, client, live_price):
        with patch(_PIPELINE):
            resp = client.post(
                "/api/forecast/start",
                json={"query": "Where will ES be in 2 hours?"},
            )
            assert resp.status_code == 202
            data = resp.json
            assert "forecast_id" in data
            assert "stream_url" in data
            assert data["stream_url"].startswith("/api/forecast/stream/")

    def test_start_rejects_empty_query(self, client):
        resp = client.post("/api/forecast/start", json={"query": ""})
        assert resp.status_code == 400
        assert "error" in resp.json

    def test_start_rejects_missing_query(self, client):
        resp = client.post("/api/forecast/start", json={})
        assert resp.status_code == 400

    def test_start_accepts_sim_preset(self, client, live_price):
        with patch(_PIPELINE):
            resp = client.post(
                "/api/forecast/start",
                json={
                    "query": "ES next 2 hours",
                    "sim_preset": "deep",
                },
            )
            assert resp.status_code == 202

    def test_start_validates_sim_count_range(self, client):
        resp = client.post(
            "/api/forecast/start",
            json={
                "query": "ES next 2 hours",
                "sim_count": 9999,
            },
        )
        assert resp.status_code == 400

    def test_start_accepts_valid_sim_count(self, client, live_price):
        with patch(_PIPELINE):
            resp = client.post(
                "/api/forecast/start",
                json={
                    "query": "ES next 2 hours",
                    "sim_count": 350,
                },
            )
            assert resp.status_code == 202

    def test_start_refuses_when_live_price_missing(self, client):
        """Fail closed: no live price -> 503 with a distinct code, no session, no pipeline."""
        with patch(_AGGREGATOR) as aggregator_cls, patch(_PIPELINE) as pipeline_cls:
            aggregator_cls.return_value.get_cross_asset_snapshot.return_value = CrossAssetSnapshot()
            resp = client.post(
                "/api/forecast/start",
                json={"query": "Where will ES be in 2 hours?"},
            )

        assert resp.status_code == 503
        assert resp.json["error"] == "market_data_unavailable"
        assert "Live price unavailable for ES" in resp.json["message"]
        assert "Forecast refused rather than estimated" in resp.json["message"]
        pipeline_cls.assert_not_called()


class TestForecastStream:
    def test_stream_returns_404_for_unknown_id(self, client):
        resp = client.get("/api/forecast/stream/nonexistent")
        assert resp.status_code == 404


class TestForecastSessions:
    def test_sessions_returns_list(self, client):
        resp = client.get("/api/forecast/sessions")
        assert resp.status_code == 200
        assert "active_sessions" in resp.json
        assert "count" in resp.json

"""Test ML API routes."""

from unittest.mock import MagicMock, patch


class TestMLRoutes:
    def test_train_returns_202(self, client) -> None:
        """POST /api/ml/train should return 202 Accepted."""
        with patch("mirofish_forecast.api.ml_routes.CacheClient") as mock_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cls.return_value = mock_cache

            with patch("mirofish_forecast.ml.trainer.ModelTrainer"):
                resp = client.post("/api/ml/train")
                assert resp.status_code == 202
                data = resp.get_json()
                assert data["status"] == "training_started"

    def test_train_returns_409_when_already_training(self, client) -> None:
        """POST /api/ml/train while already training returns 409."""
        with patch("mirofish_forecast.api.ml_routes.CacheClient") as mock_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = "training"
            mock_cls.return_value = mock_cache

            resp = client.post("/api/ml/train")
            assert resp.status_code == 409

    def test_status_returns_200(self, client) -> None:
        """GET /api/ml/status should return model status."""
        with patch("mirofish_forecast.api.ml_routes.CacheClient") as mock_cls:
            mock_cache = MagicMock()
            mock_cache.get.return_value = None
            mock_cls.return_value = mock_cache

            resp = client.get("/api/ml/status")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "models_available" in data

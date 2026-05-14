"""Tests for Brooks chart signed URL endpoint."""

from unittest.mock import patch


class TestBrooksChartEndpoint:
    """Verify /api/brooks/chart/<page_id> endpoint."""

    @patch("mirofish_forecast.api.brooks_routes.generate_signed_url_v4")
    def test_valid_page_returns_signed_url(self, mock_sign, client) -> None:
        """GET /api/brooks/chart/100 returns 200 with signed_url."""
        mock_sign.return_value = "https://storage.googleapis.com/signed-url-test"
        resp = client.get("/api/brooks/chart/100")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "signed_url" in data
        assert data["signed_url"].startswith("https://")
        mock_sign.assert_called_once_with(
            bucket="total-now-339022-mirofish-results",
            object_key="brooks-charts/page_0100.jpg",
            ttl_seconds=3600,
        )

    @patch("mirofish_forecast.api.brooks_routes.generate_signed_url_v4")
    def test_boundary_max_page(self, mock_sign, client) -> None:
        """GET /api/brooks/chart/5232 returns 200 (upper boundary)."""
        mock_sign.return_value = "https://storage.googleapis.com/signed-url-boundary"
        resp = client.get("/api/brooks/chart/5232")
        assert resp.status_code == 200
        mock_sign.assert_called_once()

    @patch("mirofish_forecast.api.brooks_routes.generate_signed_url_v4")
    def test_boundary_min_page(self, mock_sign, client) -> None:
        """GET /api/brooks/chart/1 returns 200 (lower boundary)."""
        mock_sign.return_value = "https://storage.googleapis.com/signed-url-min"
        resp = client.get("/api/brooks/chart/1")
        assert resp.status_code == 200
        mock_sign.assert_called_once()

    def test_page_zero_returns_400(self, client) -> None:
        """GET /api/brooks/chart/0 returns 400 (out of range)."""
        resp = client.get("/api/brooks/chart/0")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_page_above_max_returns_400(self, client) -> None:
        """GET /api/brooks/chart/5233 returns 400 (out of range)."""
        resp = client.get("/api/brooks/chart/5233")
        assert resp.status_code == 400

    def test_non_integer_returns_404(self, client) -> None:
        """GET /api/brooks/chart/foo returns 404 (Flask int converter rejects)."""
        resp = client.get("/api/brooks/chart/foo")
        # Flask's <int:> converter returns 404 for non-integer path params
        assert resp.status_code == 404

    @patch("mirofish_forecast.api.brooks_routes.generate_signed_url_v4")
    def test_gcs_failure_returns_503(self, mock_sign, client) -> None:
        """Mock GCS signing failure returns 503 without leaking error details."""
        mock_sign.side_effect = Exception("IAM ServiceAccountTokenCreator not granted")
        resp = client.get("/api/brooks/chart/100")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["error"] == "Chart temporarily unavailable"
        # Must NOT leak the IAM error
        assert "ServiceAccountTokenCreator" not in str(data)

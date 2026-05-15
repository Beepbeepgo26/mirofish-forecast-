"""Tests for GCS V4 signed URL utility."""

from unittest.mock import MagicMock, patch

from mirofish_forecast.utils.gcs_signing import generate_signed_url_v4


class TestGenerateSignedUrlV4:
    """Verify V4 signed URL generation."""

    @patch("mirofish_forecast.utils.gcs_signing.google.auth.default")
    @patch("mirofish_forecast.utils.gcs_signing.storage.Client")
    def test_generates_v4_signed_url(self, mock_client_cls, mock_auth) -> None:
        """V4 signed URL is generated with correct parameters."""
        # Simulate local dev (non-compute-engine credentials)
        mock_creds = MagicMock(spec=[])  # No compute_engine methods
        mock_auth.return_value = (mock_creds, "test-project")

        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = (
            "https://storage.googleapis.com/test-bucket/test-obj"
            "?X-Goog-Algorithm=GOOG4-RSA-SHA256"
            "&X-Goog-Date=20260513T000000Z"
            "&X-Goog-Expires=3600"
            "&X-Goog-SignedHeaders=host"
            "&X-Goog-Signature=abc123"
        )
        mock_client_cls.return_value.bucket.return_value.blob.return_value = mock_blob

        url = generate_signed_url_v4("test-bucket", "test-obj", ttl_seconds=3600)

        assert "X-Goog-Algorithm" in url
        assert "X-Goog-Expires=3600" in url
        mock_blob.generate_signed_url.assert_called_once()
        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["version"] == "v4"
        assert call_kwargs["method"] == "GET"

    @patch("mirofish_forecast.utils.gcs_signing.google.auth.default")
    @patch("mirofish_forecast.utils.gcs_signing.storage.Client")
    def test_custom_ttl(self, mock_client_cls, mock_auth) -> None:
        """TTL parameter is passed to the expiration argument."""
        mock_creds = MagicMock(spec=[])
        mock_auth.return_value = (mock_creds, "test-project")

        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://example.com"
        mock_client_cls.return_value.bucket.return_value.blob.return_value = mock_blob

        generate_signed_url_v4("bucket", "key", ttl_seconds=7200)

        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["expiration"].total_seconds() == 7200

    @patch("mirofish_forecast.utils.gcs_signing.google.auth.default")
    @patch("mirofish_forecast.utils.gcs_signing.google.auth.transport.requests.Request")
    @patch("mirofish_forecast.utils.gcs_signing.storage.Client")
    def test_compute_engine_uses_iam_signing(
        self, mock_client_cls, mock_request_cls, mock_auth
    ) -> None:
        """On compute engine, uses service_account_email + access_token."""
        from google.auth.compute_engine import Credentials as CECredentials

        mock_creds = MagicMock(spec=CECredentials)
        mock_creds.service_account_email = "sa@project.iam.gserviceaccount.com"
        mock_creds.token = "fake-token-123"
        mock_auth.return_value = (mock_creds, "test-project")

        mock_blob = MagicMock()
        mock_blob.generate_signed_url.return_value = "https://signed.url"
        mock_client_cls.return_value.bucket.return_value.blob.return_value = mock_blob

        url = generate_signed_url_v4("bucket", "key", ttl_seconds=3600)

        assert url == "https://signed.url"
        call_kwargs = mock_blob.generate_signed_url.call_args.kwargs
        assert call_kwargs["service_account_email"] == "sa@project.iam.gserviceaccount.com"
        assert call_kwargs["access_token"] == "fake-token-123"

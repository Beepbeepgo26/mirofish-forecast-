"""GCS signed URL utility — V4 signed URL generation."""

import logging
from datetime import timedelta

import google.auth
import google.auth.transport.requests
from google.auth import compute_engine
from google.cloud import storage

logger = logging.getLogger(__name__)


def generate_signed_url_v4(
    bucket: str,
    object_key: str,
    ttl_seconds: int = 3600,
) -> str:
    """Generate a V4 signed URL for a GCS object.

    Uses the IAM Credentials signBlob API for signing (no private key file
    needed). Requires the runtime SA to have
    roles/iam.serviceAccountTokenCreator on itself in production.

    Args:
        bucket: GCS bucket name.
        object_key: Object path within the bucket.
        ttl_seconds: URL validity period in seconds (default 1 hour).

    Returns:
        V4 signed URL string.

    Raises:
        Exception: If signing fails (IAM permissions, GCS unreachable, etc.)
    """
    credentials, project = google.auth.default()

    # On Cloud Run, credentials are compute_engine.Credentials (no private key).
    # We must use IAM-based signing via a signing credentials wrapper.
    if isinstance(credentials, compute_engine.Credentials):
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        # Use the storage client with explicit project
        client = storage.Client(project=project, credentials=credentials)
        blob = client.bucket(bucket).blob(object_key)

        url: str = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
            service_account_email=credentials.service_account_email,
            access_token=credentials.token,
        )
    else:
        # Local dev with service account key file or ADC
        client = storage.Client()
        blob = client.bucket(bucket).blob(object_key)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="GET",
        )

    return url

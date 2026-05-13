"""GCS signed URL utility — V4 signed URL generation."""

import logging
from datetime import timedelta

from google.cloud import storage

logger = logging.getLogger(__name__)


def generate_signed_url_v4(
    bucket: str,
    object_key: str,
    ttl_seconds: int = 3600,
) -> str:
    """Generate a V4 signed URL for a GCS object.

    Uses the IAM Credentials API for signing (no private key file needed).
    Requires the runtime SA to have roles/iam.serviceAccountTokenCreator
    on itself in production.

    Args:
        bucket: GCS bucket name.
        object_key: Object path within the bucket.
        ttl_seconds: URL validity period in seconds (default 1 hour).

    Returns:
        V4 signed URL string.

    Raises:
        Exception: If signing fails (IAM permissions, GCS unreachable, etc.)
    """
    client = storage.Client()
    blob = client.bucket(bucket).blob(object_key)

    url: str = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(seconds=ttl_seconds),
        method="GET",
    )
    return url

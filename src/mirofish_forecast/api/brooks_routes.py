"""Brooks API routes — signed URL endpoint for chart JPGs."""

import logging

from flask import Blueprint, jsonify

from mirofish_forecast.utils.gcs_signing import generate_signed_url_v4

logger = logging.getLogger(__name__)

brooks_bp = Blueprint("brooks", __name__)

# Brooks corpus page range
_MIN_PAGE = 1
_MAX_PAGE = 5232
_GCS_BUCKET = "total-now-339022-mirofish-results"
_GCS_PREFIX = "brooks-charts"


@brooks_bp.route("/chart/<int:page_id>", methods=["GET"])
def get_chart_signed_url(page_id: int) -> tuple:
    """Generate a signed URL for a Brooks chart JPG.

    Args:
        page_id: Page number (1–5232).

    Returns:
        JSON with signed_url field, or error response.
    """
    if page_id < _MIN_PAGE or page_id > _MAX_PAGE:
        return jsonify({"error": f"page_id must be between {_MIN_PAGE} and {_MAX_PAGE}"}), 400

    object_key = f"{_GCS_PREFIX}/page_{page_id:04d}.jpg"

    try:
        signed_url = generate_signed_url_v4(
            bucket=_GCS_BUCKET,
            object_key=object_key,
            ttl_seconds=3600,
        )
        return jsonify({"signed_url": signed_url})
    except Exception as e:
        logger.error(f"Failed to generate signed URL for page {page_id}: {e}", exc_info=True)
        return jsonify({"error": "Chart temporarily unavailable"}), 503

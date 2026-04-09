import logging
import uuid

from flask import Flask, g, request

logger = logging.getLogger(__name__)


def register_middleware(app: Flask) -> None:
    """Register error handlers, CORS headers, and request logging."""

    @app.before_request
    def set_request_id():
        g.request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])

    @app.after_request
    def add_headers(response):
        response.headers["X-Request-ID"] = g.get("request_id", "unknown")
        # CORS — permissive for development, tighten in production
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {error}", exc_info=True)
        return {"error": "Internal server error", "request_id": g.get("request_id")}, 500

    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Not found"}, 404

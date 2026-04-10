"""Health check endpoints for Cloud Run probes."""

from datetime import datetime

from flask import Blueprint, current_app, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/health/startup")
def startup():
    """Startup probe — confirms app booted and config loaded."""
    settings = current_app.config.get("SETTINGS")
    if settings is None:
        return jsonify({"status": "unhealthy", "reason": "settings not loaded"}), 503
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})


@health_bp.route("/health/liveness")
def liveness():
    """Liveness probe — confirms process is running."""
    return jsonify({"status": "healthy", "timestamp": datetime.utcnow().isoformat()})


@health_bp.route("/health/readiness")
def readiness():
    """Readiness probe — confirms dependencies are reachable."""
    from mirofish_forecast.data.cache import CacheClient

    settings = current_app.config["SETTINGS"]
    checks: dict[str, bool] = {}

    # Check Redis
    try:
        cache = CacheClient(settings)
        checks["redis"] = cache.health_check()
    except Exception:
        checks["redis"] = False

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    return jsonify(
        {
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat(),
        }
    ), status_code

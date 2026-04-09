from flask import Blueprint, current_app, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/health/startup")
def startup():
    """Startup probe — confirms app booted and config loaded."""
    settings = current_app.config.get("SETTINGS")
    if settings is None:
        return jsonify({"status": "unhealthy", "reason": "settings not loaded"}), 503
    return jsonify({"status": "healthy"})


@health_bp.route("/health/liveness")
def liveness():
    """Liveness probe — confirms process is running."""
    return jsonify({"status": "healthy"})


@health_bp.route("/health/readiness")
def readiness():
    """Readiness probe — confirms dependencies are reachable."""
    from mirofish_forecast.services.data_aggregator import DataAggregator

    settings = current_app.config["SETTINGS"]
    aggregator = DataAggregator(settings)
    checks = aggregator.health_check()

    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503

    return jsonify(
        {
            "status": "healthy" if all_healthy else "degraded",
            "checks": checks,
        }
    ), status_code

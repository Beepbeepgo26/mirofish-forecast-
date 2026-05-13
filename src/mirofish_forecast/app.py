import os

from mirofish_forecast.utils.logging import setup_logging

setup_logging()

from flask import Flask, send_from_directory

from mirofish_forecast.api.brooks_routes import brooks_bp
from mirofish_forecast.api.forecast_routes import forecast_bp
from mirofish_forecast.api.health import health_bp
from mirofish_forecast.api.market_routes import market_bp
from mirofish_forecast.api.middleware import register_middleware
from mirofish_forecast.api.ml_routes import ml_bp
from mirofish_forecast.config.settings import get_settings

# Resolve the frontend dist directory
# In Docker: WORKDIR is /app, so frontend/dist/ is at /app/frontend/dist/
# In local dev: relative to the source file works
_FRONTEND_DIR_CWD = os.path.abspath(os.path.join(os.getcwd(), "frontend", "dist"))
_FRONTEND_DIR_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
)
_FRONTEND_DIR = _FRONTEND_DIR_CWD if os.path.isdir(_FRONTEND_DIR_CWD) else _FRONTEND_DIR_SRC


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(
        __name__,
        static_folder=_FRONTEND_DIR if os.path.isdir(_FRONTEND_DIR) else None,
        static_url_path="",
    )

    settings = get_settings()
    app.config["SETTINGS"] = settings

    register_middleware(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(market_bp, url_prefix="/api/market")
    app.register_blueprint(forecast_bp, url_prefix="/api/forecast")
    app.register_blueprint(ml_bp, url_prefix="/api/ml")
    app.register_blueprint(brooks_bp, url_prefix="/api/brooks")

    # Serve Vue SPA — catch-all for non-API routes
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path: str):
        """Serve frontend static files, falling back to index.html for SPA routing."""
        if os.path.isdir(_FRONTEND_DIR):
            if path and os.path.isfile(os.path.join(_FRONTEND_DIR, path)):
                return send_from_directory(_FRONTEND_DIR, path)
            return send_from_directory(_FRONTEND_DIR, "index.html")
        return "Frontend not built. Run: cd frontend && npm run build", 404

    return app

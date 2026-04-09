from flask import Flask

from mirofish_forecast.api.forecast_routes import forecast_bp
from mirofish_forecast.api.health import health_bp
from mirofish_forecast.api.market_routes import market_bp
from mirofish_forecast.api.middleware import register_middleware
from mirofish_forecast.config.settings import get_settings


def create_app() -> Flask:
    """Flask application factory."""
    app = Flask(__name__)

    settings = get_settings()
    app.config["SETTINGS"] = settings

    register_middleware(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(market_bp, url_prefix="/api/market")
    app.register_blueprint(forecast_bp, url_prefix="/api/forecast")

    return app

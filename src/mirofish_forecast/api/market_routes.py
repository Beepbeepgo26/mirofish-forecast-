from flask import Blueprint, current_app, jsonify

from mirofish_forecast.services.data_aggregator import DataAggregator

market_bp = Blueprint("market", __name__)


@market_bp.route("/context")
def get_market_context():
    """GET /api/market/context — Returns full MarketContext as JSON."""
    settings = current_app.config["SETTINGS"]
    aggregator = DataAggregator(settings)
    context = aggregator.get_market_context()
    return jsonify(context.model_dump(mode="json"))

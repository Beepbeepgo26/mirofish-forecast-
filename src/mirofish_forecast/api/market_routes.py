"""Market data API endpoints."""

import json
import logging

from flask import Blueprint, current_app, jsonify, request

from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.services.data_aggregator import DataAggregator

logger = logging.getLogger(__name__)

market_bp = Blueprint("market", __name__)


@market_bp.route("/context")
def get_market_context():
    """GET /api/market/context — Returns full MarketContext as JSON."""
    settings = current_app.config["SETTINGS"]
    aggregator = DataAggregator(settings)
    context = aggregator.get_market_context()
    return jsonify(context.model_dump(mode="json"))


@market_bp.route("/ohlcv", methods=["GET"])
def get_ohlcv():
    """GET /api/market/ohlcv?instrument=ES&interval=5m&count=200

    Returns recent OHLCV bars for the chart.
    Uses yfinance with Redis caching.
    """
    instrument = request.args.get("instrument", "ES").upper()
    interval = request.args.get("interval", "5m")
    count = min(int(request.args.get("count", "200")), 500)

    # Validate interval
    valid_intervals = ["1m", "5m", "15m", "30m", "1h", "1d"]
    if interval not in valid_intervals:
        return (
            jsonify({"error": (f"Invalid interval. Must be one of: {valid_intervals}")}),
            400,
        )

    # Validate instrument
    ticker_map = {
        "ES": "ES=F",
        "NQ": "NQ=F",
        "CL": "CL=F",
        "GC": "GC=F",
    }
    ticker = ticker_map.get(instrument)
    if not ticker:
        return (
            jsonify({"error": f"Unknown instrument: {instrument}"}),
            400,
        )

    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)

    # Cache key includes instrument + interval
    cache_key = f"ohlcv:{instrument}:{interval}"
    cached = cache.get(cache_key)
    if cached:
        try:
            return jsonify(json.loads(cached))
        except Exception:
            pass

    try:
        import yfinance as yf

        # Determine period based on interval
        period_map = {
            "1m": "1d",
            "5m": "5d",
            "15m": "5d",
            "30m": "1mo",
            "1h": "1mo",
            "1d": "1y",
        }
        period = period_map.get(interval, "5d")

        data = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
        )

        if data.empty:
            return jsonify({"error": "No data available", "bars": []}), 200

        # Flatten MultiIndex columns if present (yfinance v0.2.31+)
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        # Convert to list of bar dicts (most recent `count` bars)
        bars = []
        for ts, row in data.tail(count).iterrows():
            bars.append(
                {
                    "time": int(ts.timestamp()),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row.get("Volume", 0)),
                }
            )

        result = {
            "instrument": instrument,
            "interval": interval,
            "count": len(bars),
            "bars": bars,
        }

        # Cache TTL based on interval
        ttl_map = {
            "1m": 30,
            "5m": 60,
            "15m": 120,
            "30m": 300,
            "1h": 600,
            "1d": 3600,
        }
        cache.set(cache_key, json.dumps(result), ttl_map.get(interval, 60))

        return jsonify(result)

    except Exception as e:
        logger.error(f"OHLCV fetch failed: {e}", exc_info=True)
        return jsonify({"error": str(e), "bars": []}), 500


@market_bp.route("/snapshot", methods=["GET"])
def get_market_snapshot():
    """GET /api/market/snapshot — Quick snapshot of key prices.

    Returns cross-asset prices for the header ticker.
    Uses the DataAggregator's cached context.
    """
    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)

    # Try cache first
    cached = cache.get("market:snapshot")
    if cached:
        try:
            return jsonify(json.loads(cached))
        except Exception:
            pass

    try:
        aggregator = DataAggregator(settings)
        context = aggregator.get_market_context()
        snapshot = {
            "cross_asset": {
                "es_price": context.cross_asset.es_price,
                "nq_price": context.cross_asset.nq_price,
                "dxy_price": context.cross_asset.dxy_price,
                "gld_price": context.cross_asset.gld_price,
                "crude_price": context.cross_asset.crude_price,
            },
            "vix": {
                "spot": context.vix.spot,
            },
        }
        cache.set("market:snapshot", json.dumps(snapshot), 30)
        return jsonify(snapshot)
    except Exception as e:
        logger.error(f"Snapshot fetch failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

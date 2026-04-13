"""ML training and status endpoints."""

import logging
from threading import Thread

from flask import Blueprint, current_app, jsonify

from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.ml.model_store import ModelStore

logger = logging.getLogger(__name__)

ml_bp = Blueprint("ml", __name__)


@ml_bp.route("/train", methods=["POST"])
def train_models():
    """POST /api/ml/train — Trigger model training.

    Runs in a background thread. Check status via GET /api/ml/status.
    """
    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)

    # Check if already training
    from mirofish_forecast.config import constants

    status = cache.get(constants.ML_TRAIN_STATUS_KEY)
    if status == "training":
        return jsonify({"status": "already_training"}), 409

    def _train() -> None:
        from mirofish_forecast.ml.trainer import ModelTrainer

        trainer = ModelTrainer(cache)
        trainer.train()

    thread = Thread(target=_train, daemon=True)
    thread.start()

    return jsonify({"status": "training_started"}), 202


@ml_bp.route("/status", methods=["GET"])
def model_status():
    """GET /api/ml/status — Get model training status and metadata."""
    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)
    store = ModelStore(cache)
    return jsonify(store.get_status())

"""ML training and status endpoints."""

import logging
from threading import Thread

from flask import Blueprint, current_app, jsonify, request

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

    # Capture the concrete app object (not the LocalProxy) before spawning
    app = current_app._get_current_object()

    def _train() -> None:
        with app.app_context():
            from mirofish_forecast.ml.trainer import ModelTrainer

            trainer = ModelTrainer(cache, settings=settings)
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


@ml_bp.route("/experiments", methods=["GET"])
def list_experiments():
    """GET /api/ml/experiments — List all training experiment runs."""
    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)

    from mirofish_forecast.ml.experiment_tracker import ExperimentTracker

    tracker = ExperimentTracker(cache)
    limit = int(request.args.get("limit", 20))
    runs = tracker.get_all_runs(limit=limit)

    return jsonify(
        {
            "runs": runs,
            "count": len(runs),
        }
    )


@ml_bp.route("/experiments/<run_id>", methods=["GET"])
def get_experiment(run_id: str):
    """GET /api/ml/experiments/{run_id} — Get a specific experiment run."""
    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)

    from mirofish_forecast.ml.experiment_tracker import ExperimentTracker

    tracker = ExperimentTracker(cache)
    run = tracker.get_run(run_id)

    if run is None:
        return jsonify({"error": f"Run {run_id} not found"}), 404

    return jsonify(run)


@ml_bp.route("/experiments/compare", methods=["POST"])
def compare_experiments():
    """POST /api/ml/experiments/compare — Compare multiple experiment runs.

    Request body: {"run_ids": ["abc123", "def456"]}
    """
    body = request.get_json(force=True, silent=True) or {}
    run_ids = body.get("run_ids", [])

    if len(run_ids) < 2:
        return jsonify({"error": "Provide at least 2 run_ids to compare"}), 400

    settings = current_app.config["SETTINGS"]
    cache = CacheClient(settings)

    from mirofish_forecast.ml.experiment_tracker import ExperimentTracker

    tracker = ExperimentTracker(cache)
    comparison = tracker.compare_runs(run_ids)

    return jsonify(comparison)

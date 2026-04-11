"""Forecast API endpoints — POST to start, GET to stream via SSE."""

import json
import logging
import threading
import uuid
from datetime import datetime
from queue import Empty, Queue
from threading import Thread

from flask import Blueprint, Response, current_app, jsonify, request

from mirofish_forecast.calibration.tracking import ForecastTracker
from mirofish_forecast.config import constants
from mirofish_forecast.services.pipeline import ForecastPipeline

logger = logging.getLogger(__name__)

forecast_bp = Blueprint("forecast", __name__)

# In-memory store for active forecast sessions
# Key: forecast_id, Value: {"queue": Queue, "created_at": datetime, "cancel_event": Event}
_active_sessions: dict[str, dict] = {}


def _cleanup_expired_sessions() -> None:
    """Remove sessions older than FORECAST_SESSION_TTL."""
    now = datetime.utcnow()
    expired = [
        fid
        for fid, session in _active_sessions.items()
        if (now - session["created_at"]).total_seconds() > constants.FORECAST_SESSION_TTL
    ]
    for fid in expired:
        del _active_sessions[fid]
        logger.info(f"Cleaned up expired forecast session: {fid}")


@forecast_bp.route("/start", methods=["POST"])
def start_forecast():
    """POST /api/forecast/start

    Request body:
    {
        "query": "Where will ES be at 11:30 AM?",
        "sim_preset": "standard",      // optional: "quick", "standard", "deep"
        "sim_count": null               // optional: 100-500 for custom/advanced
    }

    Returns:
    {
        "forecast_id": "abc123",
        "stream_url": "/api/forecast/stream/abc123"
    }
    """
    # Cleanup old sessions
    _cleanup_expired_sessions()

    # Check concurrent forecast limit
    if len(_active_sessions) >= constants.MAX_CONCURRENT_FORECASTS:
        return (
            jsonify(
                {
                    "error": "Too many concurrent forecasts. "
                    "Please wait for existing forecasts to complete.",
                }
            ),
            429,
        )

    # Parse request
    body = request.get_json(force=True, silent=True) or {}
    raw_query = body.get("query", "").strip()
    if not raw_query:
        return jsonify({"error": "Missing 'query' field"}), 400

    sim_preset = body.get("sim_preset", constants.DEFAULT_SIM_PRESET)
    sim_count = body.get("sim_count")

    # Validate sim_count if provided
    if sim_count is not None:
        try:
            sim_count = int(sim_count)
            if sim_count < 100 or sim_count > 500:
                return jsonify({"error": "sim_count must be between 100 and 500"}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "sim_count must be an integer"}), 400

    # Validate sim_preset
    if sim_preset not in ("quick", "standard", "deep"):
        sim_preset = constants.DEFAULT_SIM_PRESET

    # Create session with cancel event
    forecast_id = uuid.uuid4().hex[:12]
    event_queue: Queue = Queue()
    cancel_event = threading.Event()

    _active_sessions[forecast_id] = {
        "queue": event_queue,
        "created_at": datetime.utcnow(),
        "query": raw_query,
        "cancel_event": cancel_event,
    }

    # Launch pipeline in background thread
    settings = current_app.config["SETTINGS"]
    pipeline = ForecastPipeline(settings, event_queue, cancel_event=cancel_event)

    thread = Thread(
        target=pipeline.run,
        args=(raw_query,),
        kwargs={
            "forecast_id": forecast_id,
            "sim_preset": sim_preset,
            "sim_count": sim_count,
        },
        daemon=True,
    )
    thread.start()

    logger.info(f"Forecast started: id={forecast_id}, query={raw_query!r}, preset={sim_preset}")

    return (
        jsonify(
            {
                "forecast_id": forecast_id,
                "stream_url": f"/api/forecast/stream/{forecast_id}",
            }
        ),
        202,
    )


@forecast_bp.route("/stream/<forecast_id>")
def stream_forecast(forecast_id: str):
    """GET /api/forecast/stream/{forecast_id}

    SSE endpoint that streams forecast pipeline events.
    """
    session = _active_sessions.get(forecast_id)
    if session is None:
        return jsonify({"error": f"Forecast session {forecast_id} not found"}), 404

    def generate():
        queue = session["queue"]
        while True:
            try:
                event = queue.get(timeout=constants.SSE_QUEUE_TIMEOUT)
                yield f"data: {json.dumps(event)}\n\n"

                # If this was the final event, stop streaming
                stage = event.get("stage", "")
                if stage in (constants.STAGE_COMPLETE, constants.STAGE_ERROR):
                    # Clean up session after final event
                    _active_sessions.pop(forecast_id, None)
                    return

            except Empty:
                # Send keep-alive comment to prevent connection timeout
                yield ": keep-alive\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Prevent nginx/proxy buffering
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@forecast_bp.route("/cancel/<forecast_id>", methods=["POST"])
def cancel_forecast(forecast_id: str):
    """POST /api/forecast/cancel/{forecast_id} — Cancel an in-progress forecast."""
    session = _active_sessions.get(forecast_id)
    if session is None:
        return jsonify({"error": f"Forecast session {forecast_id} not found"}), 404

    cancel_event = session.get("cancel_event")
    if cancel_event:
        cancel_event.set()
        logger.info(f"Forecast cancelled: {forecast_id}")
        return jsonify({"status": "cancelled", "forecast_id": forecast_id})

    return jsonify({"error": "Session does not support cancellation"}), 400


@forecast_bp.route("/session-info", methods=["GET"])
def get_session_info_endpoint():
    """GET /api/forecast/session-info — Get current market session status."""
    from mirofish_forecast.services.session_context import get_session_info

    info = get_session_info()
    return jsonify(info.model_dump())


@forecast_bp.route("/sessions", methods=["GET"])
def list_sessions():
    """GET /api/forecast/sessions — List active forecast sessions (debug endpoint)."""
    sessions = {
        fid: {
            "query": s["query"],
            "created_at": s["created_at"].isoformat(),
            "age_seconds": (datetime.utcnow() - s["created_at"]).total_seconds(),
        }
        for fid, s in _active_sessions.items()
    }
    return jsonify({"active_sessions": sessions, "count": len(sessions)})


@forecast_bp.route("/history", methods=["GET"])
def get_forecast_history():
    """GET /api/forecast/history — List all tracked forecasts with outcomes."""
    settings = current_app.config["SETTINGS"]
    tracker = ForecastTracker(settings)

    # Check pending outcomes first
    tracker.check_all_pending()

    # Return all tracked forecasts
    records = tracker.get_all_tracked()
    return jsonify(
        {
            "forecasts": [json.loads(r.model_dump_json()) for r in records],
            "count": len(records),
            "scored": sum(1 for r in records if r.outcome_checked),
        }
    )


@forecast_bp.route("/calibration", methods=["GET"])
def get_calibration_status():
    """GET /api/forecast/calibration — Get calibration metrics and status."""
    from mirofish_forecast.calibration.reliability import (
        compute_calibration_summary,
        compute_reliability_diagram_data,
    )

    settings = current_app.config["SETTINGS"]
    tracker = ForecastTracker(settings)

    # Check pending outcomes
    tracker.check_all_pending()

    all_tracked = tracker.get_all_tracked()
    summary = compute_calibration_summary(all_tracked)
    diagram = compute_reliability_diagram_data(all_tracked)

    return jsonify(
        {
            "summary": summary,
            "reliability_diagram": diagram,
        }
    )


@forecast_bp.route("/check-outcomes", methods=["POST"])
def check_outcomes():
    """POST /api/forecast/check-outcomes

    Trigger outcome checking for all pending forecasts.
    Called by Cloud Scheduler every 30 minutes.
    Can also be called manually.
    """
    settings = current_app.config["SETTINGS"]
    tracker = ForecastTracker(settings)

    checked = tracker.check_all_pending()

    return jsonify(
        {
            "checked": len(checked),
            "results": [
                {
                    "forecast_id": r.forecast_id,
                    "direction_correct": r.direction_correct,
                    "absolute_error": r.absolute_error,
                    "actual_price": r.actual_price,
                }
                for r in checked
            ],
        }
    )

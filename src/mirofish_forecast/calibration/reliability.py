"""Reliability diagrams and calibration metrics.

Computes Expected Calibration Error (ECE) and generates
data for reliability diagram visualization.
"""

import logging

import numpy as np

from mirofish_forecast.config import constants
from mirofish_forecast.models.forecast import ForecastTracking

logger = logging.getLogger(__name__)


def compute_ece(
    forecasts: list[ForecastTracking],
    num_bins: int = constants.RELIABILITY_NUM_BINS,
) -> float:
    """Compute Expected Calibration Error for direction forecasts.

    ECE measures how well predicted probabilities match observed frequencies.
    ECE = sum(|fraction_correct - mean_confidence| * bin_size / total)

    Args:
        forecasts: Scored forecast records
        num_bins: Number of bins for calibration

    Returns:
        ECE value (0.0 = perfectly calibrated, 1.0 = maximally miscalibrated)
    """
    if not forecasts:
        return 0.0

    scored = [f for f in forecasts if f.outcome_checked and f.direction_correct is not None]
    if len(scored) < 10:
        return 0.0

    # Use the max direction probability as the confidence
    confidences_list: list[float] = []
    correct_list: list[float] = []
    for f in scored:
        conf = max(f.predicted_prob_up, f.predicted_prob_down, f.predicted_prob_flat)
        confidences_list.append(conf)
        correct_list.append(1.0 if f.direction_correct else 0.0)

    confidences = np.array(confidences_list)
    correct = np.array(correct_list)

    bin_edges = np.linspace(0, 1, num_bins + 1)
    ece = 0.0

    for i in range(num_bins):
        mask = (confidences > bin_edges[i]) & (confidences <= bin_edges[i + 1])
        if not np.any(mask):
            continue
        bin_conf = float(np.mean(confidences[mask]))
        bin_acc = float(np.mean(correct[mask]))
        bin_size = int(np.sum(mask))
        ece += abs(bin_acc - bin_conf) * bin_size

    return float(ece / len(scored))


def compute_interval_coverage(
    forecasts: list[ForecastTracking],
) -> dict[str, float]:
    """Compute observed coverage for prediction intervals.

    Returns:
        Dict with coverage at different levels
    """
    scored = [f for f in forecasts if f.outcome_checked and f.actual_price is not None]
    if not scored:
        return {"p50_coverage": 0.0, "p90_coverage": 0.0}

    p50_hits = sum(1 for f in scored if f.p50_hit) / len(scored)
    p90_hits = sum(1 for f in scored if f.p90_hit) / len(scored)

    return {
        "p50_coverage": round(p50_hits, 3),  # Should be ~50%
        "p90_coverage": round(p90_hits, 3),  # Should be ~90%
        "sample_size": float(len(scored)),
    }


def compute_reliability_diagram_data(
    forecasts: list[ForecastTracking],
    num_bins: int = constants.RELIABILITY_NUM_BINS,
) -> list[dict]:
    """Generate data points for a reliability diagram.

    Each bin contains:
    - mean_predicted: average predicted confidence in this bin
    - mean_actual: fraction of correct predictions in this bin
    - count: number of forecasts in this bin

    A perfectly calibrated model produces points on the y=x diagonal.
    """
    scored = [f for f in forecasts if f.outcome_checked and f.direction_correct is not None]
    if len(scored) < 10:
        return []

    confidences_list: list[float] = []
    correct_list: list[float] = []
    for f in scored:
        conf = max(f.predicted_prob_up, f.predicted_prob_down, f.predicted_prob_flat)
        confidences_list.append(conf)
        correct_list.append(1.0 if f.direction_correct else 0.0)

    confidences = np.array(confidences_list)
    correct = np.array(correct_list)

    bin_edges = np.linspace(0, 1, num_bins + 1)
    diagram_data: list[dict] = []

    for i in range(num_bins):
        mask = (confidences > bin_edges[i]) & (confidences <= bin_edges[i + 1])
        if not np.any(mask):
            continue
        diagram_data.append(
            {
                "bin_start": round(float(bin_edges[i]), 2),
                "bin_end": round(float(bin_edges[i + 1]), 2),
                "mean_predicted": round(float(np.mean(confidences[mask])), 3),
                "mean_actual": round(float(np.mean(correct[mask])), 3),
                "count": int(np.sum(mask)),
            }
        )

    return diagram_data


def compute_calibration_summary(forecasts: list[ForecastTracking]) -> dict:
    """Compute a complete calibration summary."""
    scored = [f for f in forecasts if f.outcome_checked]

    if not scored:
        return {
            "total_forecasts": len(forecasts),
            "scored_forecasts": 0,
            "pending_forecasts": len(forecasts),
            "calibration_ready": False,
        }

    direction_correct = [f for f in scored if f.direction_correct]
    coverage = compute_interval_coverage(scored)

    # Directional accuracy excluding abstentions (confidence-filtered)
    directional_forecasts = [
        f
        for f in scored
        if f.predicted_prob_up is not None
        and f.predicted_prob_down is not None
        and max(f.predicted_prob_up, f.predicted_prob_down)
        >= constants.ML_DIRECTION_CONFIDENCE_THRESHOLD
    ]
    if directional_forecasts:
        dir_correct_confident = sum(1 for f in directional_forecasts if f.direction_correct)
        direction_accuracy_confident = round(dir_correct_confident / len(directional_forecasts), 4)
        direction_confident_count = len(directional_forecasts)
    else:
        direction_accuracy_confident = None
        direction_confident_count = 0

    return {
        "total_forecasts": len(forecasts),
        "scored_forecasts": len(scored),
        "pending_forecasts": len(forecasts) - len(scored),
        "calibration_ready": len(scored) >= constants.CALIBRATION_MIN_SAMPLES,
        "direction_accuracy": round(len(direction_correct) / max(len(scored), 1), 3),
        "direction_accuracy_confident": direction_accuracy_confident,
        "direction_confident_count": direction_confident_count,
        "mean_absolute_error": round(
            sum(f.absolute_error for f in scored if f.absolute_error is not None)
            / max(len(scored), 1),
            2,
        ),
        "p50_coverage": coverage.get("p50_coverage", 0),
        "p90_coverage": coverage.get("p90_coverage", 0),
        "ece": compute_ece(scored),
        "sample_size": len(scored),
    }

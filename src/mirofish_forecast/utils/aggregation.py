"""Statistical aggregation utilities — logarithmic pooling and distribution analysis.

Logarithmic pooling is the aggregation method used by Metaculus and the
Good Judgment Project. It respects confident predictions more than
linear averaging and minimizes average KL divergence to expert opinions.
"""

import logging
import math

import numpy as np
from scipy import stats as sp_stats

from mirofish_forecast.config import constants

logger = logging.getLogger(__name__)


def logarithmic_pool_probabilities(
    probabilities: list[float],
    weights: list[float] | None = None,
    extremizing_factor: float = constants.LOG_POOL_EXTREMIZING_FACTOR,
) -> float:
    """Aggregate multiple probability estimates using logarithmic pooling.

    This converts each probability to log-odds, takes the weighted average,
    applies an extremizing correction, and converts back to probability.

    Args:
        probabilities: List of probability estimates (0.01 to 0.99)
        weights: Optional weights for each estimate (defaults to uniform)
        extremizing_factor: d ≈ 1.5–2.0, corrects for underconfidence

    Returns:
        Aggregated probability (0.01 to 0.99)
    """
    if not probabilities:
        return 0.5

    # Clamp to avoid log(0) and log(inf)
    clamped = [max(0.01, min(0.99, p)) for p in probabilities]

    if weights is None:
        weights = [1.0 / len(clamped)] * len(clamped)
    else:
        total = sum(weights)
        weights = [w / total for w in weights]

    # Convert to log-odds, take weighted average
    log_odds = [math.log(p / (1 - p)) for p in clamped]
    weighted_log_odds = sum(w * lo for w, lo in zip(weights, log_odds, strict=False))

    # Apply extremizing factor
    extremized = weighted_log_odds * extremizing_factor

    # Convert back to probability
    result = 1.0 / (1.0 + math.exp(-extremized))
    return max(0.01, min(0.99, result))


def compute_distribution_stats(
    final_prices: list[float],
    current_price: float,
) -> dict:
    """Compute distribution statistics from Monte Carlo simulation results.

    Args:
        final_prices: List of final prices from each simulation
        current_price: Starting price for direction classification

    Returns:
        Dictionary of statistics for ProbabilityDistribution model
    """
    arr = np.array(final_prices)

    if len(arr) < 2:
        return {
            "median": current_price,
            "mean": current_price,
            "std_dev": 0.0,
            "percentile_5": current_price,
            "percentile_25": current_price,
            "percentile_75": current_price,
            "percentile_95": current_price,
            "skewness": 0.0,
            "prob_up": 0.33,
            "prob_down": 0.33,
            "prob_flat": 0.34,
        }

    flat_threshold = current_price * 0.001  # 0.1% = "flat"

    return {
        "median": round(float(np.median(arr)), 2),
        "mean": round(float(np.mean(arr)), 2),
        "std_dev": round(float(np.std(arr)), 2),
        "percentile_5": round(float(np.percentile(arr, 5)), 2),
        "percentile_25": round(float(np.percentile(arr, 25)), 2),
        "percentile_75": round(float(np.percentile(arr, 75)), 2),
        "percentile_95": round(float(np.percentile(arr, 95)), 2),
        "skewness": round(float(sp_stats.skew(arr)), 3),
        "prob_up": round(float(np.mean(arr > current_price + flat_threshold)), 3),
        "prob_down": round(float(np.mean(arr < current_price - flat_threshold)), 3),
        "prob_flat": round(
            float(
                np.mean(
                    (arr >= current_price - flat_threshold)
                    & (arr <= current_price + flat_threshold)
                )
            ),
            3,
        ),
    }


def compute_scenario_probabilities(
    final_prices: list[float],
    scenarios: list[dict],
) -> dict[str, float]:
    """Compute realized probabilities for each scenario based on simulation results.

    Classifies each simulation's final price into the scenario whose price range
    it falls within, then returns the fraction in each.

    Args:
        final_prices: List of final prices from simulations
        scenarios: List of scenario dicts with 'rank', 'price_range_low', 'price_range_high'

    Returns:
        Dict mapping scenario rank to realized probability
    """
    if not final_prices or not scenarios:
        return {}

    arr = np.array(final_prices)
    result: dict[str, float] = {}

    for scenario in scenarios:
        rank = scenario.get("rank", "unknown")
        low = scenario.get("price_range_low")
        high = scenario.get("price_range_high")

        if low is not None and high is not None:
            count = int(np.sum((arr >= low) & (arr <= high)))
            result[rank] = round(count / len(arr), 3)
        else:
            result[rank] = 0.0

    # Assign any unclassified sims to the most probable scenario
    classified = sum(result.values())
    if classified < 1.0 and scenarios:
        most_probable_rank = scenarios[0].get("rank", "most_probable")
        result[most_probable_rank] = round(
            result.get(most_probable_rank, 0) + (1.0 - classified), 3
        )

    return result

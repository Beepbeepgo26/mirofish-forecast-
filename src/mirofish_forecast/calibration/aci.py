"""Adaptive Conformal Inference — online self-correcting calibration.

ACI adjusts alpha (miscoverage rate) after each forecast:
- If the interval missed: alpha decreases (intervals widen)
- If the interval covered: alpha increases (intervals tighten)

This handles non-stationarity in financial data where the distribution
shifts over time (regime changes, vol shifts).
"""

import logging

from mirofish_forecast.config import constants

logger = logging.getLogger(__name__)


class ACITracker:
    """Adaptive Conformal Inference — online alpha adjustment."""

    def __init__(self) -> None:
        self._alpha = constants.ACI_INITIAL_ALPHA
        self._history: list[dict] = []  # Recent coverage observations

    @property
    def current_alpha(self) -> float:
        """Current miscoverage rate."""
        return self._alpha

    @property
    def current_coverage_target(self) -> float:
        """Current coverage target (1 - alpha)."""
        return 1 - self._alpha

    def update(self, was_covered: bool) -> float:
        """Update alpha based on whether the last interval covered the actual.

        Args:
            was_covered: True if actual price was within the prediction interval

        Returns:
            Updated alpha value
        """
        # ACI update rule: alpha_{t+1} = alpha_t + gamma * (alpha - err_t)
        # where err_t = 1 if missed, 0 if covered
        err = 0.0 if was_covered else 1.0
        self._alpha = self._alpha + constants.ACI_GAMMA * (constants.ACI_INITIAL_ALPHA - err)

        # Clamp to valid range
        self._alpha = max(constants.ACI_MIN_ALPHA, min(constants.ACI_MAX_ALPHA, self._alpha))

        self._history.append(
            {
                "was_covered": was_covered,
                "alpha_after": self._alpha,
            }
        )

        # Keep only last 500 observations
        if len(self._history) > 500:
            self._history = self._history[-500:]

        logger.debug(f"ACI update: covered={was_covered}, alpha={self._alpha:.4f}")
        return self._alpha

    def get_recent_coverage(self, window: int = 50) -> float:
        """Compute observed coverage over the last N forecasts."""
        if not self._history:
            return 0.0
        recent = self._history[-window:]
        return sum(1 for h in recent if h["was_covered"]) / len(recent)

    def get_interval_multiplier(self) -> float:
        """Get a multiplier for interval width based on current alpha.

        Higher alpha = narrower intervals (more confident)
        Lower alpha = wider intervals (less confident)
        """
        # Baseline: alpha=0.10 → multiplier=1.0
        # If alpha drops to 0.05 → multiplier=1.3 (wider)
        # If alpha rises to 0.20 → multiplier=0.7 (narrower)
        return constants.ACI_INITIAL_ALPHA / max(self._alpha, 0.01)

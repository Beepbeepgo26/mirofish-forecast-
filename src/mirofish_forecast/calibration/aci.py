"""Adaptive Conformal Inference — online self-correcting calibration.

ACI adjusts alpha (miscoverage rate) after each forecast:
- If the interval missed: alpha decreases (intervals widen)
- If the interval covered: alpha increases (intervals tighten)

This handles non-stationarity in financial data where the distribution
shifts over time (regime changes, vol shifts).

Alpha is persisted in Redis so it survives Cloud Run cold starts.
"""

import logging

from mirofish_forecast.config import constants
from mirofish_forecast.data.cache import CacheClient

logger = logging.getLogger(__name__)

# Redis keys for persisted ACI state
ACI_ALPHA_KEY = "calibration:aci_alpha"
ACI_HISTORY_KEY = "calibration:aci_history_count"


class ACITracker:
    """Adaptive Conformal Inference — online alpha adjustment with Redis persistence."""

    def __init__(self, cache: CacheClient | None = None) -> None:
        self._cache = cache
        self._alpha = self._load_alpha()
        self._update_count = self._load_update_count()

    @property
    def current_alpha(self) -> float:
        """Current miscoverage rate."""
        return self._alpha

    @property
    def current_coverage_target(self) -> float:
        """Current coverage target (1 - alpha)."""
        return 1 - self._alpha

    @property
    def update_count(self) -> int:
        """Total number of ACI updates applied."""
        return self._update_count

    def update(self, was_covered: bool) -> float:
        """Update alpha based on whether the last interval covered the actual.

        Args:
            was_covered: True if actual price was within the prediction interval

        Returns:
            Updated alpha value
        """
        # ACI update rule: alpha_{t+1} = alpha_t + gamma * (alpha_target - err_t)
        err = 0.0 if was_covered else 1.0
        self._alpha = self._alpha + constants.ACI_GAMMA * (constants.ACI_INITIAL_ALPHA - err)

        # Clamp to valid range
        self._alpha = max(
            constants.ACI_MIN_ALPHA,
            min(constants.ACI_MAX_ALPHA, self._alpha),
        )

        self._update_count += 1

        # Persist to Redis
        self._save_alpha()

        logger.debug(
            f"ACI update #{self._update_count}: covered={was_covered}, alpha={self._alpha:.4f}"
        )
        return self._alpha

    def get_recent_coverage(self, window: int = 50) -> float | None:
        """Not available without in-memory history. Returns None.

        Use compute_interval_coverage() from reliability.py for coverage stats.
        """
        return None

    def get_interval_multiplier(self) -> float:
        """Get a multiplier for interval width based on current alpha.

        Higher alpha = narrower intervals (more confident)
        Lower alpha = wider intervals (less confident)
        """
        return constants.ACI_INITIAL_ALPHA / max(self._alpha, 0.01)

    def reset(self) -> None:
        """Reset alpha to initial value."""
        self._alpha = constants.ACI_INITIAL_ALPHA
        self._update_count = 0
        self._save_alpha()
        logger.info("ACI alpha reset to initial value")

    # --- Redis persistence ---

    def _load_alpha(self) -> float:
        """Load alpha from Redis, or return initial value."""
        if self._cache is None:
            return constants.ACI_INITIAL_ALPHA
        try:
            raw = self._cache.get(ACI_ALPHA_KEY)
            if raw is not None:
                return float(raw)
        except Exception:
            logger.warning("Failed to load ACI alpha from Redis", exc_info=True)
        return constants.ACI_INITIAL_ALPHA

    def _load_update_count(self) -> int:
        """Load update count from Redis."""
        if self._cache is None:
            return 0
        try:
            raw = self._cache.get(ACI_HISTORY_KEY)
            if raw is not None:
                return int(raw)
        except Exception:
            pass
        return 0

    def _save_alpha(self) -> None:
        """Persist alpha and update count to Redis."""
        if self._cache is None:
            return
        try:
            ttl = 86400 * 365  # Effectively permanent
            self._cache.set(ACI_ALPHA_KEY, str(round(self._alpha, 6)), ttl)
            self._cache.set(ACI_HISTORY_KEY, str(self._update_count), ttl)
        except Exception:
            logger.warning("Failed to save ACI alpha to Redis", exc_info=True)

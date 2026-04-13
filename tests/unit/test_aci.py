"""Test Adaptive Conformal Inference with Redis persistence."""

from unittest.mock import MagicMock

from mirofish_forecast.calibration.aci import (
    ACI_ALPHA_KEY,
    ACI_HISTORY_KEY,
    ACITracker,
)


class TestACITrackerInMemory:
    """Tests for ACITracker without cache (in-memory fallback)."""

    def test_initial_alpha(self) -> None:
        aci = ACITracker()
        assert aci.current_alpha == 0.10
        assert aci.current_coverage_target == 0.90

    def test_miss_widens_intervals(self) -> None:
        aci = ACITracker()
        initial = aci.current_alpha
        aci.update(was_covered=False)
        # After a miss, alpha should decrease (wider intervals)
        assert aci.current_alpha < initial

    def test_hit_narrows_intervals(self) -> None:
        aci = ACITracker()
        initial = aci.current_alpha
        aci.update(was_covered=True)
        # After a hit, alpha should increase (narrower intervals)
        assert aci.current_alpha > initial

    def test_alpha_clamped(self) -> None:
        aci = ACITracker()
        # Many misses should not push alpha below minimum
        for _ in range(100):
            aci.update(was_covered=False)
        assert aci.current_alpha >= 0.02

        # Many hits should not push alpha above maximum
        for _ in range(100):
            aci.update(was_covered=True)
        assert aci.current_alpha <= 0.30

    def test_interval_multiplier(self) -> None:
        aci = ACITracker()
        base_mult = aci.get_interval_multiplier()
        assert abs(base_mult - 1.0) < 0.01

        # After misses, multiplier should increase (wider intervals)
        for _ in range(20):
            aci.update(was_covered=False)
        assert aci.get_interval_multiplier() > 1.0

    def test_recent_coverage_returns_none_without_history(self) -> None:
        aci = ACITracker()
        assert aci.get_recent_coverage() is None

    def test_update_count_tracks(self) -> None:
        aci = ACITracker()
        assert aci.update_count == 0
        aci.update(was_covered=True)
        assert aci.update_count == 1
        aci.update(was_covered=False)
        assert aci.update_count == 2


class TestACIRedis:
    """Tests for ACITracker with Redis persistence."""

    def test_loads_alpha_from_cache(self) -> None:
        """Should restore alpha from Redis on init."""
        cache = MagicMock()
        cache.get.side_effect = lambda key: {
            ACI_ALPHA_KEY: "0.07",
            ACI_HISTORY_KEY: "15",
        }.get(key)

        aci = ACITracker(cache=cache)
        assert aci.current_alpha == 0.07
        assert aci.update_count == 15

    def test_saves_alpha_to_cache(self) -> None:
        """Should persist alpha to Redis after update."""
        cache = MagicMock()
        cache.get.return_value = None

        aci = ACITracker(cache=cache)
        aci.update(was_covered=True)

        # Should have called set with alpha key
        set_calls = cache.set.call_args_list
        alpha_calls = [c for c in set_calls if ACI_ALPHA_KEY in str(c)]
        assert len(alpha_calls) > 0

    def test_cold_start_continuity(self) -> None:
        """Two instances with same cache should share state."""
        cache = MagicMock()
        saved_state: dict[str, str] = {}

        def mock_set(key: str, value: str, ttl: int) -> None:
            saved_state[key] = value

        def mock_get(key: str) -> str | None:
            return saved_state.get(key)

        cache.set.side_effect = mock_set
        cache.get.side_effect = mock_get

        # Instance 1: do some updates
        aci1 = ACITracker(cache=cache)
        for _ in range(5):
            aci1.update(was_covered=True)
        alpha_after = aci1.current_alpha

        # Instance 2: cold start — should pick up same alpha
        import pytest
        aci2 = ACITracker(cache=cache)
        assert aci2.current_alpha == pytest.approx(alpha_after, abs=1e-5)
        assert aci2.update_count == 5

    def test_none_cache_fallback(self) -> None:
        """cache=None should work without errors."""
        aci = ACITracker(cache=None)
        assert aci.current_alpha == 0.10
        aci.update(was_covered=True)
        assert aci.update_count == 1

    def test_reset_persists(self) -> None:
        """Reset should write initial alpha to Redis."""
        cache = MagicMock()
        cache.get.return_value = "0.05"

        aci = ACITracker(cache=cache)
        aci.reset()

        assert aci.current_alpha == 0.10
        assert aci.update_count == 0
        # Should have persisted the reset
        cache.set.assert_called()

    def test_handles_redis_failure_gracefully(self) -> None:
        """Should not crash if Redis is down."""
        cache = MagicMock()
        cache.get.side_effect = Exception("Redis connection refused")
        cache.set.side_effect = Exception("Redis connection refused")

        aci = ACITracker(cache=cache)
        assert aci.current_alpha == 0.10  # Fallback to default

        # Should not raise
        aci.update(was_covered=True)

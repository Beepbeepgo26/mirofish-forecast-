"""Test Adaptive Conformal Inference."""

from mirofish_forecast.calibration.aci import ACITracker


class TestACITracker:
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

    def test_recent_coverage(self) -> None:
        aci = ACITracker()
        for _ in range(40):
            aci.update(was_covered=True)
        for _ in range(10):
            aci.update(was_covered=False)
        coverage = aci.get_recent_coverage(window=50)
        assert 0.7 < coverage < 0.9  # ~80% of last 50 were covered

    def test_interval_multiplier(self) -> None:
        aci = ACITracker()
        base_mult = aci.get_interval_multiplier()
        assert abs(base_mult - 1.0) < 0.01  # At default alpha, multiplier ~1.0

        # After misses, multiplier should increase (wider intervals)
        for _ in range(20):
            aci.update(was_covered=False)
        assert aci.get_interval_multiplier() > 1.0

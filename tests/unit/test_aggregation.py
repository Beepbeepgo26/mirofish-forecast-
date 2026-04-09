"""Test aggregation utilities — logarithmic pooling and distribution stats."""

from mirofish_forecast.utils.aggregation import (
    compute_distribution_stats,
    compute_scenario_probabilities,
    logarithmic_pool_probabilities,
)


class TestLogarithmicPooling:
    def test_uniform_probabilities(self):
        """Equal probabilities should return ~0.5 regardless of extremizing."""
        result = logarithmic_pool_probabilities([0.5, 0.5, 0.5])
        assert abs(result - 0.5) < 0.01

    def test_strong_consensus_amplified(self):
        """If all experts agree on high probability, pooling should preserve or amplify."""
        result = logarithmic_pool_probabilities([0.9, 0.85, 0.88])
        assert result > 0.85

    def test_mixed_signals_moderate(self):
        """Mixed signals should produce a moderate probability."""
        result = logarithmic_pool_probabilities([0.9, 0.1, 0.5])
        assert 0.3 < result < 0.7

    def test_weights_respect_confident_expert(self):
        """Higher weight on a confident expert should shift the result."""
        equal_weights = logarithmic_pool_probabilities([0.9, 0.5], weights=[0.5, 0.5])
        skewed_weights = logarithmic_pool_probabilities([0.9, 0.5], weights=[0.8, 0.2])
        assert skewed_weights > equal_weights

    def test_clamping_prevents_extremes(self):
        """Output should always be between 0.01 and 0.99."""
        result = logarithmic_pool_probabilities([0.99, 0.99, 0.99], extremizing_factor=3.0)
        assert result <= 0.99
        assert result >= 0.01

    def test_single_probability(self):
        result = logarithmic_pool_probabilities([0.7])
        assert 0.5 < result < 0.95

    def test_empty_returns_half(self):
        assert logarithmic_pool_probabilities([]) == 0.5


class TestDistributionStats:
    def test_basic_stats(self):
        prices = [5410.0, 5420.0, 5430.0, 5415.0, 5425.0]
        stats = compute_distribution_stats(prices, 5420.0)
        assert stats["median"] == 5420.0
        assert stats["percentile_5"] < stats["percentile_95"]
        assert stats["prob_up"] + stats["prob_down"] + stats["prob_flat"] <= 1.01

    def test_single_price(self):
        stats = compute_distribution_stats([5420.0], 5420.0)
        assert stats["median"] == 5420.0
        assert stats["std_dev"] == 0.0

    def test_bullish_distribution(self):
        prices = [5430.0 + i for i in range(100)]
        stats = compute_distribution_stats(prices, 5420.0)
        assert stats["prob_up"] > 0.9

    def test_bearish_distribution(self):
        prices = [5410.0 - i for i in range(100)]
        stats = compute_distribution_stats(prices, 5420.0)
        assert stats["prob_down"] > 0.9


class TestScenarioProbabilities:
    def test_basic_classification(self):
        prices = [5420.0] * 60 + [5450.0] * 30 + [5370.0] * 10
        scenarios = [
            {
                "rank": "most_probable",
                "price_range_low": 5400,
                "price_range_high": 5440,
            },
            {
                "rank": "secondary",
                "price_range_low": 5440,
                "price_range_high": 5460,
            },
            {
                "rank": "failure_trap",
                "price_range_low": 5360,
                "price_range_high": 5400,
            },
        ]
        probs = compute_scenario_probabilities(prices, scenarios)
        assert probs["most_probable"] > 0.5
        assert probs["secondary"] > 0.2

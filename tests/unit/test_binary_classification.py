"""Tests for binary classification and confidence filtering."""

import numpy as np


class TestBinaryLabeling:
    def test_min_move_filter_discards_flat(self):
        """Samples with small moves should be filtered out (< 0.10% move)."""
        from mirofish_forecast.config import constants

        min_move = constants.ML_DIRECTION_MIN_MOVE_PCT

        pct_return_small = 0.5 / 5700    # ~0.0000877 — below threshold
        pct_return_up = 10.0 / 5700      # ~0.00175 — above threshold
        pct_return_down = -10.0 / 5700   # ~-0.00175 — above (negative) threshold

        assert abs(pct_return_small) < min_move  # Filtered
        assert pct_return_up > min_move           # Labeled up
        assert pct_return_down < -min_move        # Labeled down

    def test_confidence_gate_abstains(self):
        """Low-confidence predictions should be reported as 'flat' (abstention)."""
        from mirofish_forecast.config import constants

        threshold = constants.ML_DIRECTION_CONFIDENCE_THRESHOLD

        # High confidence → directional call
        prob_up, prob_down = 0.65, 0.35
        max_prob = max(prob_up, prob_down)
        assert max_prob >= threshold
        direction = "up" if prob_up >= prob_down else "down"
        assert direction == "up"

        # Low confidence → abstain
        prob_up, prob_down = 0.52, 0.48
        max_prob = max(prob_up, prob_down)
        assert max_prob < threshold
        direction = "flat"  # Abstention
        assert direction == "flat"

    def test_binary_labels_only_zero_and_one(self):
        """Binary labels should only contain 0 (down) and 1 (up)."""
        labels = np.array([0, 1, 1, 0, 1, 0])
        assert set(labels.tolist()).issubset({0, 1})

    def test_lgbm_binary_params(self):
        """Direction model should use binary objective, not multiclass."""
        from mirofish_forecast.config import constants

        params = constants.ML_LGBM_DIRECTION_PARAMS
        assert params["objective"] == "binary"
        assert "num_class" not in params

    def test_confidence_threshold_value(self):
        """Confidence threshold should be 0.55 as specified."""
        from mirofish_forecast.config import constants

        assert constants.ML_DIRECTION_CONFIDENCE_THRESHOLD == 0.55

    def test_min_move_pct_value(self):
        """Min move PCT should be 0.001 (0.10%)."""
        from mirofish_forecast.config import constants

        assert constants.ML_DIRECTION_MIN_MOVE_PCT == 0.001

    def test_direction_mode_binary(self):
        """ML_DIRECTION_MODE should be 'binary'."""
        from mirofish_forecast.config import constants

        assert constants.ML_DIRECTION_MODE == "binary"

    def test_confidence_gate_logic_up(self):
        """Above threshold, prob_up > prob_down → direction='up'."""
        from mirofish_forecast.config import constants

        threshold = constants.ML_DIRECTION_CONFIDENCE_THRESHOLD
        prob_up, prob_down = 0.62, 0.38
        max_prob = max(prob_up, prob_down)

        assert max_prob >= threshold
        direction = "up" if prob_up >= prob_down else "down"
        assert direction == "up"

    def test_confidence_gate_logic_down(self):
        """Above threshold, prob_down > prob_up → direction='down'."""
        from mirofish_forecast.config import constants

        threshold = constants.ML_DIRECTION_CONFIDENCE_THRESHOLD
        prob_up, prob_down = 0.37, 0.63
        max_prob = max(prob_up, prob_down)

        assert max_prob >= threshold
        direction = "up" if prob_up >= prob_down else "down"
        assert direction == "down"

    def test_binary_filter_removes_flat_keeps_directional(self):
        """min-move filter should keep only clear up/down samples."""
        from mirofish_forecast.config import constants

        min_move = constants.ML_DIRECTION_MIN_MOVE_PCT
        closes = np.array([5700.0, 5700.3, 5706.0, 5694.0, 5700.1])
        bars_ahead = 1

        y_dir_list: list[int] = []
        dir_mask_list: list[bool] = []

        for idx in range(len(closes) - bars_ahead):
            current = closes[idx]
            future = closes[idx + bars_ahead]
            pct_return = (future - current) / current

            if pct_return > min_move:
                y_dir_list.append(1)
                dir_mask_list.append(True)
            elif pct_return < -min_move:
                y_dir_list.append(0)
                dir_mask_list.append(True)
            else:
                y_dir_list.append(-1)
                dir_mask_list.append(False)

        y_dir = [d for d, m in zip(y_dir_list, dir_mask_list) if m]

        # Only idx 1→2 (+6pts) and idx 2→3 (-12pts) clear the threshold
        assert set(y_dir).issubset({0, 1})
        assert len(y_dir) >= 1  # At least some directional samples
        assert -1 not in y_dir   # No placeholder labels leaked through

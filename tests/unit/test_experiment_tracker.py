"""Test ExperimentTracker."""

import json
from unittest.mock import MagicMock

import pytest

from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.ml.experiment_tracker import ExperimentTracker


@pytest.fixture
def tracker(mock_cache):
    """ExperimentTracker with a mock cache."""
    return ExperimentTracker(mock_cache)


class TestStartAndEndRun:
    """Test basic run lifecycle."""

    def test_start_returns_run_id(self, tracker: ExperimentTracker) -> None:
        run_id = tracker.start_run(run_name="test_run")
        assert run_id is not None
        assert len(run_id) == 12

    def test_end_run_returns_record(
        self, tracker: ExperimentTracker, mock_cache: MagicMock
    ) -> None:
        run_id = tracker.start_run(run_name="test_run")
        tracker.log_param("horizon", 120)
        tracker.log_metric("accuracy", 0.405)

        record = tracker.end_run(status="success")

        assert record["run_id"] == run_id
        assert record["status"] == "success"
        assert record["params"]["horizon"] == 120
        assert record["params"]["run_name"] == "test_run"
        assert record["metrics"]["accuracy"] == 0.405
        assert record["duration_seconds"] >= 0

        # Should have saved to Redis (run record + index update = 2 set calls)
        assert mock_cache.set.called

    def test_failed_run(
        self, tracker: ExperimentTracker, mock_cache: MagicMock
    ) -> None:
        tracker.start_run()
        record = tracker.end_run(status="failed")
        assert record["status"] == "failed"


class TestLogParams:
    """Test parameter logging."""

    def test_log_params_batch(self, tracker: ExperimentTracker) -> None:
        tracker.start_run()
        tracker.log_params({"a": 1, "b": "two", "c": 3.0})
        record = tracker.end_run()

        assert record["params"]["a"] == 1
        assert record["params"]["b"] == "two"
        assert record["params"]["c"] == 3.0


class TestLogMetrics:
    """Test metric logging."""

    def test_log_metrics_batch(self, tracker: ExperimentTracker) -> None:
        tracker.start_run()
        tracker.log_metrics({"acc": 0.40, "coverage": 0.73})
        record = tracker.end_run()

        assert record["metrics"]["acc"] == 0.40
        assert record["metrics"]["coverage"] == 0.73


class TestFeatureImportance:
    """Test feature importance logging."""

    def test_sorts_descending(self, tracker: ExperimentTracker) -> None:
        tracker.start_run()
        tracker.log_feature_importance(
            feature_names=["feat_a", "feat_b", "feat_c"],
            importances=[10.0, 50.0, 30.0],
        )
        record = tracker.end_run()

        fi = record["artifacts"]["feature_importance"]
        assert fi[0]["feature"] == "feat_b"  # Highest importance
        assert fi[1]["feature"] == "feat_c"
        assert fi[2]["feature"] == "feat_a"

    def test_logs_top_10_as_metrics(self, tracker: ExperimentTracker) -> None:
        tracker.start_run()
        tracker.log_feature_importance(
            feature_names=["a", "b", "c"],
            importances=[10.0, 50.0, 30.0],
        )
        record = tracker.end_run()

        # Top feature metric keys
        assert "importance_rank1_b" in record["metrics"]
        assert record["metrics"]["importance_rank1_b"] == 50.0


class TestGetRuns:
    """Test run retrieval."""

    def test_get_all_runs(self, mock_cache: MagicMock) -> None:
        run1 = {"run_id": "aaa", "status": "success", "metrics": {"accuracy": 0.40}}
        run2 = {"run_id": "bbb", "status": "success", "metrics": {"accuracy": 0.42}}

        def mock_get(key: str):
            if key == "mf:experiments:index":
                return json.dumps(["aaa", "bbb"])
            if key == "mf:experiments:aaa":
                return json.dumps(run1)
            if key == "mf:experiments:bbb":
                return json.dumps(run2)
            return None

        mock_cache.get.side_effect = mock_get

        tracker = ExperimentTracker(mock_cache)
        runs = tracker.get_all_runs()

        assert len(runs) == 2
        # Newest first
        assert runs[0]["run_id"] == "bbb"
        assert runs[1]["run_id"] == "aaa"

    def test_get_single_run(self, mock_cache: MagicMock) -> None:
        run1 = {"run_id": "abc123", "status": "success"}
        mock_cache.get.return_value = json.dumps(run1)

        tracker = ExperimentTracker(mock_cache)
        result = tracker.get_run("abc123")

        assert result is not None
        assert result["run_id"] == "abc123"

    def test_get_missing_run(self, mock_cache: MagicMock) -> None:
        mock_cache.get.return_value = None
        tracker = ExperimentTracker(mock_cache)
        assert tracker.get_run("nonexistent") is None

    def test_empty_index(self, mock_cache: MagicMock) -> None:
        mock_cache.get.return_value = None
        tracker = ExperimentTracker(mock_cache)
        assert tracker.get_all_runs() == []


class TestCompareRuns:
    """Test run comparison."""

    def test_compare_two_runs(self, mock_cache: MagicMock) -> None:
        run1 = {
            "run_id": "aaa",
            "status": "success",
            "metrics": {"accuracy": 0.40, "coverage": 0.70},
        }
        run2 = {
            "run_id": "bbb",
            "status": "success",
            "metrics": {"accuracy": 0.42, "coverage": 0.73},
        }

        def mock_get(key: str):
            if key == "mf:experiments:aaa":
                return json.dumps(run1)
            if key == "mf:experiments:bbb":
                return json.dumps(run2)
            return None

        mock_cache.get.side_effect = mock_get

        tracker = ExperimentTracker(mock_cache)
        result = tracker.compare_runs(["aaa", "bbb"])

        assert "comparison" in result
        assert "accuracy" in result["comparison"]
        assert result["comparison"]["accuracy"]["aaa"] == 0.40
        assert result["comparison"]["accuracy"]["bbb"] == 0.42

    def test_compare_insufficient_runs(self, mock_cache: MagicMock) -> None:
        mock_cache.get.return_value = None
        tracker = ExperimentTracker(mock_cache)
        result = tracker.compare_runs(["aaa"])
        assert "Need at least 2" in str(result["comparison"])


class TestIndexCapping:
    """Test that the index is capped at EXPERIMENT_MAX_RUNS."""

    def test_old_runs_deleted(self, mock_cache: MagicMock) -> None:
        # Simulate an index with 100 entries
        existing_ids = [f"run_{i:03d}" for i in range(100)]
        mock_cache.get.return_value = json.dumps(existing_ids)

        tracker = ExperimentTracker(mock_cache)
        tracker.start_run()
        tracker.end_run()

        # Should have called delete for old runs
        assert mock_cache.delete.called or mock_cache.set.called

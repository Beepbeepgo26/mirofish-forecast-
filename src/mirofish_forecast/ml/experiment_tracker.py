"""Experiment tracking — logs training runs with params, metrics, and artifacts.

Uses MLflow for auto-capturing LightGBM internals during training,
then persists the run summary to Redis for API access. This works
on Cloud Run where there's no persistent filesystem — MLflow writes
to a temp dir that lives for the duration of the training thread.
"""

import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone

from mirofish_forecast.config import constants
from mirofish_forecast.data.cache import CacheClient

logger = logging.getLogger(__name__)


class ExperimentTracker:
    """Tracks ML training experiments in Redis."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache
        self._run_id: str | None = None
        self._params: dict = {}
        self._metrics: dict = {}
        self._artifacts: dict = {}
        self._start_time: datetime | None = None
        self._mlflow_dir: str | None = None

    def start_run(self, run_name: str | None = None) -> str:
        """Start a new experiment run.

        Sets up MLflow with a temp tracking directory and enables
        LightGBM autologging.

        Returns:
            The run ID.
        """
        self._run_id = uuid.uuid4().hex[:12]
        self._params = {}
        self._metrics = {}
        self._artifacts = {}
        self._start_time = datetime.now(timezone.utc)

        if run_name:
            self._params["run_name"] = run_name

        # Set up MLflow with temp directory
        self._mlflow_dir = tempfile.mkdtemp(prefix="mlflow_")

        try:
            import mlflow

            mlflow.set_tracking_uri(f"file://{self._mlflow_dir}")
            mlflow.set_experiment("mirofish-forecast")

            # Enable LightGBM autologging
            # This auto-captures: n_estimators, learning_rate, num_leaves,
            # max_depth, feature_importance, training metrics, etc.
            mlflow.lightgbm.autolog(
                log_input_examples=False,
                log_model_signatures=False,
                log_models=False,  # Don't save model artifacts (we use Redis)
            )

            mlflow.start_run(run_name=run_name or f"train_{self._run_id}")

            logger.info(f"Experiment run started: {self._run_id}")
        except Exception:
            logger.warning(
                "MLflow setup failed, continuing without autolog",
                exc_info=True,
            )

        return self._run_id

    def log_param(self, key: str, value: object) -> None:
        """Log a parameter."""
        self._params[key] = value
        try:
            import mlflow

            mlflow.log_param(key, value)
        except Exception:
            pass

    def log_params(self, params: dict) -> None:
        """Log multiple parameters."""
        for k, v in params.items():
            self.log_param(k, v)

    def log_metric(self, key: str, value: float) -> None:
        """Log a metric."""
        self._metrics[key] = value
        try:
            import mlflow

            mlflow.log_metric(key, value)
        except Exception:
            pass

    def log_metrics(self, metrics: dict[str, float]) -> None:
        """Log multiple metrics."""
        for k, v in metrics.items():
            self.log_metric(k, v)

    def log_feature_importance(
        self, feature_names: list[str], importances: list[float]
    ) -> None:
        """Log feature importance as a sorted list."""
        pairs = sorted(
            zip(feature_names, importances),
            key=lambda x: x[1],
            reverse=True,
        )
        self._artifacts["feature_importance"] = [
            {"feature": name, "importance": round(float(imp), 4)}
            for name, imp in pairs
        ]
        # Also log top 10 as individual metrics for easy comparison
        for i, (name, imp) in enumerate(pairs[:10]):
            self.log_metric(
                f"importance_rank{i + 1}_{name}", round(float(imp), 4)
            )

    def end_run(self, status: str = "success") -> dict:
        """End the run, persist summary to Redis, and clean up.

        Args:
            status: "success", "failed", or "error".

        Returns:
            The complete run record.
        """
        end_time = datetime.now(timezone.utc)
        duration = (
            (end_time - self._start_time).total_seconds()
            if self._start_time
            else 0
        )

        # Extract any additional MLflow-captured data
        mlflow_auto_params = self._extract_mlflow_data()

        # Merge auto-captured params (don't overwrite manually logged ones)
        for k, v in mlflow_auto_params.get("params", {}).items():
            if k not in self._params:
                self._params[k] = v

        for k, v in mlflow_auto_params.get("metrics", {}).items():
            if k not in self._metrics:
                self._metrics[k] = v

        # End MLflow run
        try:
            import mlflow

            mlflow.end_run()
        except Exception:
            pass

        # Build run record
        run_record: dict = {
            "run_id": self._run_id,
            "status": status,
            "started_at": (
                self._start_time.isoformat() if self._start_time else None
            ),
            "ended_at": end_time.isoformat(),
            "duration_seconds": round(duration, 1),
            "params": self._params,
            "metrics": self._metrics,
            "artifacts": self._artifacts,
        }

        # Persist to Redis
        self._save_run(run_record)

        # Clean up temp dir
        if self._mlflow_dir:
            try:
                shutil.rmtree(self._mlflow_dir, ignore_errors=True)
            except Exception:
                pass

        logger.info(
            f"Experiment run ended: {self._run_id}, "
            f"status={status}, duration={duration:.1f}s"
        )
        return run_record

    def get_run(self, run_id: str) -> dict | None:
        """Retrieve a specific run record."""
        key = f"{constants.EXPERIMENT_PREFIX}:{run_id}"
        raw = self._cache.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def get_all_runs(self, limit: int = 50) -> list[dict]:
        """Retrieve all experiment runs, newest first."""
        index_raw = self._cache.get(constants.EXPERIMENT_INDEX_KEY)
        if not index_raw:
            return []

        try:
            run_ids = json.loads(index_raw)
        except Exception:
            return []

        runs: list[dict] = []
        for run_id in reversed(run_ids[-limit:]):
            run = self.get_run(run_id)
            if run:
                runs.append(run)

        return runs

    def compare_runs(self, run_ids: list[str]) -> dict:
        """Compare metrics across multiple runs.

        Returns:
            Dict with run_id → metrics mapping and a diff summary.
        """
        runs: dict[str, dict] = {}
        for run_id in run_ids:
            run = self.get_run(run_id)
            if run:
                runs[run_id] = run

        if len(runs) < 2:
            return {
                "runs": runs,
                "comparison": "Need at least 2 runs to compare",
            }

        # Find common metrics across all runs
        all_metric_keys: set[str] = set()
        for run in runs.values():
            all_metric_keys.update(run.get("metrics", {}).keys())

        comparison: dict[str, dict] = {}
        for metric_key in sorted(all_metric_keys):
            values: dict[str, float] = {}
            for run_id, run in runs.items():
                val = run.get("metrics", {}).get(metric_key)
                if val is not None:
                    values[run_id] = val
            if values:
                comparison[metric_key] = values

        return {"runs": runs, "comparison": comparison}

    def _save_run(self, run_record: dict) -> None:
        """Persist a run record to Redis and update the index."""
        run_id = run_record["run_id"]

        # Save the run
        key = f"{constants.EXPERIMENT_PREFIX}:{run_id}"
        self._cache.set(
            key, json.dumps(run_record), constants.EXPERIMENT_TTL
        )

        # Update the index
        index_raw = self._cache.get(constants.EXPERIMENT_INDEX_KEY)
        if index_raw:
            try:
                run_ids = json.loads(index_raw)
            except Exception:
                run_ids = []
        else:
            run_ids = []

        if run_id not in run_ids:
            run_ids.append(run_id)

        # Keep only the last N runs
        if len(run_ids) > constants.EXPERIMENT_MAX_RUNS:
            # Delete old run records
            for old_id in run_ids[: -constants.EXPERIMENT_MAX_RUNS]:
                old_key = f"{constants.EXPERIMENT_PREFIX}:{old_id}"
                self._cache.delete(old_key)
            run_ids = run_ids[-constants.EXPERIMENT_MAX_RUNS :]

        self._cache.set(
            constants.EXPERIMENT_INDEX_KEY,
            json.dumps(run_ids),
            constants.EXPERIMENT_TTL,
        )

    def _extract_mlflow_data(self) -> dict:
        """Extract auto-logged params and metrics from the MLflow temp dir.

        Returns:
            Dict with "params" and "metrics" sub-dicts.
        """
        result: dict[str, dict] = {"params": {}, "metrics": {}}

        if not self._mlflow_dir:
            return result

        try:
            import mlflow

            client = mlflow.tracking.MlflowClient(
                tracking_uri=f"file://{self._mlflow_dir}"
            )

            # Get the active run
            runs = client.search_runs(experiment_ids=["0"])
            if not runs:
                return result

            run = runs[0]

            # Extract params
            for k, v in run.data.params.items():
                result["params"][k] = v

            # Extract metrics
            for k, v in run.data.metrics.items():
                result["metrics"][k] = v

        except Exception:
            logger.debug(
                "Failed to extract MLflow auto-logged data", exc_info=True
            )

        return result

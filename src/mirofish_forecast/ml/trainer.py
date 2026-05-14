"""Offline training pipeline — builds LightGBM models from historical data.

Pulls 1 year of hourly ES bars from yfinance, computes features at each bar,
generates forward-looking labels, and trains three models:
1. Direction classifier (up/down/flat)
2. Quantile regressor P5
3. Quantile regressor P95
"""

import logging
from datetime import datetime, timedelta

import numpy as np

from mirofish_forecast.config import constants
from mirofish_forecast.config.settings import Settings
from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.data.databento_client import DatabentoClient
from mirofish_forecast.ml.experiment_tracker import ExperimentTracker
from mirofish_forecast.ml.feature_extractor import (
    FEATURE_NAMES,
    FeatureExtractor,
)
from mirofish_forecast.ml.model_store import ModelStore

logger = logging.getLogger(__name__)

# Indices of cross-asset features to exclude from direction model
# These are indices 21, 22, 23 in the canonical FEATURE_NAMES ordering
_CROSS_ASSET_INDICES = [21, 22, 23]


class ModelTrainer:
    """Trains LightGBM models on historical ES data."""

    def __init__(self, cache: CacheClient, settings: Settings = None) -> None:
        self._cache = cache
        self._store = ModelStore(cache)
        self._extractor = FeatureExtractor()
        self._experiment = ExperimentTracker(cache)
        if settings is None:
            from flask import current_app

            settings = current_app.config["SETTINGS"]
        self._databento = DatabentoClient(settings, cache)

    def train(
        self,
        horizon_minutes: int = constants.ML_DEFAULT_HORIZON,
    ) -> dict:
        """Run the full training pipeline.

        Args:
            horizon_minutes: Forecast horizon for label generation

        Returns:
            Dict with training results and metrics
        """
        self._cache.set(constants.ML_TRAIN_STATUS_KEY, "training", 3600)

        try:
            # Start experiment tracking
            self._experiment.start_run(
                run_name=f"train_h{horizon_minutes}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}"
            )
            self._experiment.log_params(
                {
                    "horizon_minutes": horizon_minutes,
                    "lookback_days": constants.ML_TRAINING_LOOKBACK_DAYS,
                    "min_samples": constants.ML_MIN_TRAINING_SAMPLES,
                    "direction_mode": constants.ML_DIRECTION_MODE,
                    "min_move_pct": constants.ML_DIRECTION_MIN_MOVE_PCT,
                    "confidence_threshold": constants.ML_DIRECTION_CONFIDENCE_THRESHOLD,
                    "feature_count": len(FEATURE_NAMES),
                }
            )

            # Step 1: Fetch historical data
            logger.info("Fetching historical data for training...")
            data = self._fetch_data()
            if data is None:
                self._cache.set(
                    constants.ML_TRAIN_STATUS_KEY,
                    "failed:no_data",
                    86400,
                )
                self._experiment.end_run(status="failed")
                return {
                    "success": False,
                    "error": "No historical data available",
                }

            closes, highs, lows, opens, volumes, dxy_closes, tlt_closes, crude_closes = data
            logger.info(f"Fetched {len(closes)} hourly bars")

            self._experiment.log_params(
                {
                    "training_bars": len(closes),
                    "has_dxy_data": bool(np.any(dxy_closes != 0)),
                    "has_tlt_data": bool(np.any(tlt_closes != 0)),
                    "has_crude_data": bool(np.any(crude_closes != 0)),
                }
            )

            # Step 2: Build feature matrix + labels
            logger.info("Extracting features and labels...")
            x_all, y_dir, y_ret, x_dir, dir_mask = self._build_dataset(
                closes,
                highs,
                lows,
                opens,
                volumes,
                horizon_minutes,
                dxy_closes=dxy_closes,
                tlt_closes=tlt_closes,
                crude_closes=crude_closes,
            )

            total_samples = x_all.shape[0]
            dir_samples = x_dir.shape[0] if x_dir.size else 0
            filtered_pct = round((1 - dir_samples / max(total_samples, 1)) * 100, 1)
            logger.info(
                f"Dataset: {total_samples} total samples, "
                f"{dir_samples} directional samples ({filtered_pct}% filtered as flat)"
            )

            if dir_samples < constants.ML_MIN_TRAINING_SAMPLES:
                self._cache.set(
                    constants.ML_TRAIN_STATUS_KEY,
                    "failed:insufficient_directional_data",
                    86400,
                )
                return {
                    "success": False,
                    "error": (
                        f"Only {dir_samples} directional samples,"
                        f" need {constants.ML_MIN_TRAINING_SAMPLES}"
                    ),
                }

            # Step 3: Train/test split (time-series: last 20%)
            # Direction model: split filtered samples
            dir_split = int(dir_samples * 0.8)
            x_dir_train, x_dir_test = x_dir[:dir_split], x_dir[dir_split:]
            y_dir_train, y_dir_test = y_dir[:dir_split], y_dir[dir_split:]

            # Quantile models: split ALL samples (including flat-filtered)
            all_split = int(total_samples * 0.8)
            x_all_train, x_all_test = x_all[:all_split], x_all[all_split:]
            y_ret_train, y_ret_test = y_ret[:all_split], y_ret[all_split:]

            self._experiment.log_params(
                {
                    "train_samples_dir": int(x_dir_train.shape[0]),
                    "test_samples_dir": int(x_dir_test.shape[0]),
                    "train_samples_all": int(x_all_train.shape[0]),
                    "test_samples_all": int(x_all_test.shape[0]),
                    "split_ratio": 0.8,
                }
            )

            # Step 4: Train binary direction classifier (exclude cross-asset features)
            import lightgbm as lgb

            logger.info(
                f"Training binary direction classifier "
                f"({dir_samples} samples, {x_dir_train.shape[1] - len(_CROSS_ASSET_INDICES)} features)..."
            )
            keep_mask = np.ones(x_dir_train.shape[1], dtype=bool)
            keep_mask[_CROSS_ASSET_INDICES] = False
            x_dir_train_trimmed = x_dir_train[:, keep_mask]
            x_dir_test_trimmed = x_dir_test[:, keep_mask]

            dir_model = lgb.LGBMClassifier(**constants.ML_LGBM_DIRECTION_PARAMS)
            dir_model.fit(x_dir_train_trimmed, y_dir_train)

            # Evaluate direction accuracy
            dir_preds = dir_model.predict(x_dir_test_trimmed)
            dir_accuracy = float(np.mean(dir_preds == y_dir_test))

            # Evaluate confidence-filtered accuracy
            dir_probs = dir_model.predict_proba(x_dir_test_trimmed)
            max_probs = np.max(dir_probs, axis=1)
            conf_mask_eval = max_probs >= constants.ML_DIRECTION_CONFIDENCE_THRESHOLD
            conf_count = int(np.sum(conf_mask_eval))

            if conf_count > 0:
                conf_accuracy = float(
                    np.mean(dir_preds[conf_mask_eval] == y_dir_test[conf_mask_eval])
                )
                conf_pct = round(conf_count / len(dir_preds) * 100, 1)
            else:
                conf_accuracy = 0.0
                conf_pct = 0.0

            logger.info(
                f"Direction accuracy: {dir_accuracy:.4f} (all), "
                f"{conf_accuracy:.4f} (confidence-filtered, {conf_pct}% of predictions)"
            )

            self._experiment.log_metrics(
                {
                    "direction_accuracy": round(dir_accuracy, 4),
                    "confidence_filtered_accuracy": round(conf_accuracy, 4),
                    "confidence_filtered_pct": conf_pct,
                }
            )

            # Log direction model feature importance
            if hasattr(dir_model, "feature_importances_"):
                dir_feature_names = [
                    n for i, n in enumerate(FEATURE_NAMES) if i not in _CROSS_ASSET_INDICES
                ]
                self._experiment.log_feature_importance(
                    dir_feature_names,
                    dir_model.feature_importances_.tolist(),
                )

            # Step 5: Train quantile regressors (all samples, all features)
            logger.info("Training quantile regressors...")
            q_low = lgb.LGBMRegressor(**constants.ML_LGBM_QUANTILE_LOW_PARAMS)
            q_low.fit(x_all_train, y_ret_train)

            q_high = lgb.LGBMRegressor(**constants.ML_LGBM_QUANTILE_HIGH_PARAMS)
            q_high.fit(x_all_train, y_ret_train)

            # Step 6: Evaluate quantile coverage on test set
            q_low_preds = q_low.predict(x_all_test)
            q_high_preds = q_high.predict(x_all_test)
            coverage = float(np.mean((y_ret_test >= q_low_preds) & (y_ret_test <= q_high_preds)))

            self._experiment.log_metrics(
                {
                    "interval_coverage": round(coverage, 4),
                    "total_samples": int(x_all.shape[0]),
                    "direction_samples": int(dir_samples),
                    "filtered_as_flat_pct": filtered_pct,
                }
            )

            # Step 7: Save models to Redis
            now = datetime.utcnow().isoformat()
            base_meta = {
                "trained_at": now,
                "samples": int(total_samples),
                "horizon_minutes": horizon_minutes,
            }

            self._store.save_model(
                constants.ML_DIRECTION_MODEL_KEY,
                dir_model,
                {
                    **base_meta,
                    "accuracy": round(dir_accuracy, 4),
                    "confidence_filtered_accuracy": round(conf_accuracy, 4),
                    "confidence_threshold": constants.ML_DIRECTION_CONFIDENCE_THRESHOLD,
                    "confidence_filtered_pct": conf_pct,
                    "direction_samples": dir_samples,
                    "filtered_pct": filtered_pct,
                    "features": int(x_dir_train_trimmed.shape[1]),
                    "mode": "binary",
                    "min_move_pct": constants.ML_DIRECTION_MIN_MOVE_PCT,
                },
            )
            self._store.save_model(
                constants.ML_QUANTILE_LOW_KEY,
                q_low,
                {**base_meta, "quantile": 0.05},
            )
            self._store.save_model(
                constants.ML_QUANTILE_HIGH_KEY,
                q_high,
                {
                    **base_meta,
                    "quantile": 0.95,
                    "coverage": round(coverage, 4),
                },
            )
            self._store.save_feature_names(FEATURE_NAMES)

            self._cache.set(
                constants.ML_TRAIN_STATUS_KEY,
                "complete",
                86400 * 30,
            )

            result = {
                "success": True,
                "samples": int(total_samples),
                "direction_samples": int(dir_samples),
                "filtered_as_flat_pct": filtered_pct,
                "train_samples_dir": int(x_dir_train.shape[0]),
                "test_samples_dir": int(x_dir_test.shape[0]),
                "direction_accuracy": round(dir_accuracy, 4),
                "confidence_filtered_accuracy": round(conf_accuracy, 4),
                "confidence_threshold": constants.ML_DIRECTION_CONFIDENCE_THRESHOLD,
                "confidence_filtered_pct": conf_pct,
                "interval_coverage": round(coverage, 4),
                "horizon_minutes": horizon_minutes,
                "direction_mode": "binary",
                "trained_at": now,
            }
            # End experiment tracking
            run_record = self._experiment.end_run(status="success")
            result["experiment_run_id"] = run_record["run_id"]

            logger.info(f"Training complete: {result}")
            return result

        except Exception as e:
            logger.error("Training failed", exc_info=True)
            try:
                self._experiment.end_run(status="failed")
            except Exception:
                pass
            self._cache.set(
                constants.ML_TRAIN_STATUS_KEY,
                f"failed:{str(e)[:100]}",
                86400,
            )
            return {"success": False, "error": str(e)}

    def _fetch_data(
        self,
    ) -> (
        tuple[
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
            np.ndarray,
        ]
        | None
    ):
        """Fetch 1 year of hourly bars for ES + cross-asset tickers.

        Returns:
            Tuple of (closes, highs, lows, opens, volumes,
                      dxy_closes, tlt_closes, crude_closes)
            or None if fetch fails.
        """
        try:
            import yfinance as yf

            end = datetime.utcnow()
            start = end - timedelta(days=constants.ML_TRAINING_LOOKBACK_DAYS)
            start_str = start.strftime("%Y-%m-%d")
            end_str = end.strftime("%Y-%m-%d")

            # Try Databento for ES data
            db_data = None
            if self._databento.is_enabled:
                db_data = self._databento.get_training_data(
                    instrument="ES",
                    lookback_days=constants.ML_TRAINING_LOOKBACK_DAYS,
                    schema="ohlcv-1h",
                )

            if db_data is not None:
                closes, highs, lows, opens, volumes = db_data
            else:
                logger.info("Falling back to yfinance for training data")
                # Fetch ES OHLCV
                es_data = yf.download(
                    "ES=F",
                    start=start_str,
                    end=end_str,
                    interval="1h",
                    progress=False,
                )

                if es_data.empty or len(es_data) < 200:
                    return None

                if hasattr(es_data.columns, "levels"):
                    es_data.columns = es_data.columns.get_level_values(0)

                closes = es_data["Close"].values.flatten().astype(np.float64)
                highs = es_data["High"].values.flatten().astype(np.float64)
                lows = es_data["Low"].values.flatten().astype(np.float64)
                opens = es_data["Open"].values.flatten().astype(np.float64)
                volumes = es_data["Volume"].values.flatten().astype(np.float64)

            n = len(closes)

            # Fetch cross-asset close prices (best-effort)
            dxy_closes = np.zeros(n, dtype=np.float64)
            tlt_closes = np.zeros(n, dtype=np.float64)
            crude_closes = np.zeros(n, dtype=np.float64)

            cross_tickers = {
                "DX-Y.NYB": "dxy",
                "TLT": "tlt",
                "CL=F": "crude",
            }

            for ticker, name in cross_tickers.items():
                try:
                    data = yf.download(
                        ticker,
                        start=start_str,
                        end=end_str,
                        interval="1h",
                        progress=False,
                    )
                    if data.empty:
                        logger.warning(f"No data for {ticker}, using zeros")
                        continue

                    if hasattr(data.columns, "levels"):
                        data.columns = data.columns.get_level_values(0)

                    cross_closes = data["Close"].values.flatten().astype(np.float64)

                    # Align to ES timestamps (use min length)
                    aligned_len = min(len(cross_closes), n)
                    if name == "dxy":
                        dxy_closes[-aligned_len:] = cross_closes[-aligned_len:]
                    elif name == "tlt":
                        tlt_closes[-aligned_len:] = cross_closes[-aligned_len:]
                    elif name == "crude":
                        crude_closes[-aligned_len:] = cross_closes[-aligned_len:]

                    logger.info(f"Fetched {len(cross_closes)} bars for {ticker}")
                except Exception:
                    logger.warning(
                        f"Failed to fetch {ticker}",
                        exc_info=True,
                    )

            return (
                closes,
                highs,
                lows,
                opens,
                volumes,
                dxy_closes,
                tlt_closes,
                crude_closes,
            )

        except Exception:
            logger.error("Failed to fetch training data", exc_info=True)
            return None

    def _build_dataset(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        opens: np.ndarray,
        volumes: np.ndarray,
        horizon_minutes: int,
        dxy_closes: np.ndarray | None = None,
        tlt_closes: np.ndarray | None = None,
        crude_closes: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Build feature matrix and label vectors.

        Returns:
            x_all: Feature matrix for ALL samples (used by quantile models)
            y_dir: Binary direction labels (0=down, 1=up) for FILTERED samples only
            y_ret: Future price for ALL samples (used by quantile models)
            x_dir: Feature matrix for FILTERED samples only (direction model)
            dir_mask: Boolean mask of which samples passed the minimum move filter
        """
        bars_ahead = max(1, horizon_minutes // 60)
        max_idx = len(closes) - bars_ahead - 1
        start_idx = constants.FEATURE_OHLCV_LOOKBACK

        if max_idx <= start_idx:
            empty = np.array([], dtype=np.float32)
            return empty, empty, empty, empty, np.array([], dtype=bool)

        x_list: list[np.ndarray] = []
        y_dir_list: list[int] = []
        y_ret_list: list[float] = []
        dir_mask_list: list[bool] = []

        min_move = constants.ML_DIRECTION_MIN_MOVE_PCT

        for idx in range(start_idx, max_idx):
            features = self._extractor.extract_from_historical(
                closes,
                highs,
                lows,
                opens,
                volumes,
                idx=idx,
                horizon_minutes=horizon_minutes,
                dxy_closes=dxy_closes,
                tlt_closes=tlt_closes,
                crude_closes=crude_closes,
            )
            x_list.append(features)

            current = closes[idx]
            future = closes[idx + bars_ahead]
            pct_return = (future - current) / current

            y_ret_list.append(float(future))

            # Binary labeling with minimum move filter
            if pct_return > min_move:
                y_dir_list.append(1)  # up
                dir_mask_list.append(True)
            elif pct_return < -min_move:
                y_dir_list.append(0)  # down
                dir_mask_list.append(True)
            else:
                y_dir_list.append(-1)  # placeholder — filtered out below
                dir_mask_list.append(False)

        x_all = np.array(x_list, dtype=np.float32)
        y_ret = np.array(y_ret_list, dtype=np.float32)
        dir_mask = np.array(dir_mask_list, dtype=bool)

        # Filter to directional samples only
        x_dir = x_all[dir_mask]
        y_dir = np.array(
            [d for d, m in zip(y_dir_list, dir_mask_list) if m],
            dtype=np.int32,
        )

        return x_all, y_dir, y_ret, x_dir, dir_mask

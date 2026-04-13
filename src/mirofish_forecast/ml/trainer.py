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
from mirofish_forecast.data.cache import CacheClient
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

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache
        self._store = ModelStore(cache)
        self._extractor = FeatureExtractor()

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
            # Step 1: Fetch historical data
            logger.info("Fetching historical data for training...")
            data = self._fetch_data()
            if data is None:
                self._cache.set(
                    constants.ML_TRAIN_STATUS_KEY,
                    "failed:no_data",
                    86400,
                )
                return {
                    "success": False,
                    "error": "No historical data available",
                }

            closes, highs, lows, opens, volumes, dxy_closes, tlt_closes, crude_closes = data
            logger.info(f"Fetched {len(closes)} hourly bars")

            # Step 2: Build feature matrix + labels
            logger.info("Extracting features and labels...")
            x_arr, y_dir, y_ret = self._build_dataset(
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
            logger.info(f"Dataset: {x_arr.shape[0]} samples, {x_arr.shape[1]} features")

            if x_arr.shape[0] < constants.ML_MIN_TRAINING_SAMPLES:
                self._cache.set(
                    constants.ML_TRAIN_STATUS_KEY,
                    "failed:insufficient_data",
                    86400,
                )
                return {
                    "success": False,
                    "error": (
                        f"Only {x_arr.shape[0]} samples, need {constants.ML_MIN_TRAINING_SAMPLES}"
                    ),
                }

            # Step 3: Train/test split (time-series: last 20%)
            split_idx = int(x_arr.shape[0] * 0.8)
            x_train, x_test = x_arr[:split_idx], x_arr[split_idx:]
            y_dir_train = y_dir[:split_idx]
            y_dir_test = y_dir[split_idx:]
            y_ret_train = y_ret[:split_idx]
            y_ret_test = y_ret[split_idx:]

            # Step 4: Train direction classifier (exclude cross-asset features)
            import lightgbm as lgb

            logger.info("Training direction classifier (22 features, no cross-asset)...")
            # Build trimmed arrays without cross-asset columns
            keep_mask = np.ones(x_train.shape[1], dtype=bool)
            keep_mask[_CROSS_ASSET_INDICES] = False
            x_train_dir = x_train[:, keep_mask]
            x_test_dir = x_test[:, keep_mask]

            dir_model = lgb.LGBMClassifier(**constants.ML_LGBM_DIRECTION_PARAMS)
            dir_model.fit(x_train_dir, y_dir_train)
            dir_accuracy = float(np.mean(dir_model.predict(x_test_dir) == y_dir_test))

            # Step 5: Train quantile regressors (full 25 features)
            logger.info("Training quantile regressors...")
            q_low = lgb.LGBMRegressor(**constants.ML_LGBM_QUANTILE_LOW_PARAMS)
            q_low.fit(x_train, y_ret_train)

            q_high = lgb.LGBMRegressor(**constants.ML_LGBM_QUANTILE_HIGH_PARAMS)
            q_high.fit(x_train, y_ret_train)

            # Step 6: Evaluate on test set
            q_low_preds = q_low.predict(x_test)
            q_high_preds = q_high.predict(x_test)
            coverage = float(np.mean((y_ret_test >= q_low_preds) & (y_ret_test <= q_high_preds)))

            # Step 7: Save models to Redis
            now = datetime.utcnow().isoformat()
            base_meta = {
                "trained_at": now,
                "samples": int(x_arr.shape[0]),
                "features": int(x_arr.shape[1]),
                "horizon_minutes": horizon_minutes,
            }

            self._store.save_model(
                constants.ML_DIRECTION_MODEL_KEY,
                dir_model,
                {
                    **base_meta,
                    "accuracy": round(dir_accuracy, 4),
                    "features": int(x_train_dir.shape[1]),
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
                "samples": int(x_arr.shape[0]),
                "train_samples": int(x_train.shape[0]),
                "test_samples": int(x_test.shape[0]),
                "direction_accuracy": round(dir_accuracy, 4),
                "interval_coverage": round(coverage, 4),
                "horizon_minutes": horizon_minutes,
                "trained_at": now,
            }
            logger.info(f"Training complete: {result}")
            return result

        except Exception as e:
            logger.error("Training failed", exc_info=True)
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
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Build feature matrix and label vectors.

        Labels:
        - y_direction: 0=down, 1=flat, 2=up
        - y_return: actual future price (for quantile regression)
        """
        bars_ahead = max(1, horizon_minutes // 60)
        max_idx = len(closes) - bars_ahead - 1
        start_idx = constants.FEATURE_OHLCV_LOOKBACK

        if max_idx <= start_idx:
            return np.array([]), np.array([]), np.array([])

        x_list: list[np.ndarray] = []
        y_dir_list: list[int] = []
        y_ret_list: list[float] = []

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

            flat_thr = current * constants.ML_DIRECTION_FLAT_THRESHOLD
            if future > current + flat_thr:
                direction = 2  # up
            elif future < current - flat_thr:
                direction = 0  # down
            else:
                direction = 1  # flat

            y_dir_list.append(direction)
            y_ret_list.append(float(future))

        return (
            np.array(x_list, dtype=np.float32),
            np.array(y_dir_list, dtype=np.int32),
            np.array(y_ret_list, dtype=np.float32),
        )

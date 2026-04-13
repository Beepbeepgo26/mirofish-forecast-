"""Redis-backed model persistence for LightGBM models."""

import json
import logging
import pickle

from mirofish_forecast.config import constants
from mirofish_forecast.data.cache import CacheClient

logger = logging.getLogger(__name__)


class ModelStore:
    """Serializes and deserializes LightGBM models to/from Redis."""

    def __init__(self, cache: CacheClient) -> None:
        self._cache = cache

    def save_model(
        self,
        key: str,
        model: object,
        metadata: dict | None = None,
    ) -> bool:
        """Serialize a LightGBM model to Redis.

        Args:
            key: Redis key for the model
            model: Trained LightGBM model object
            metadata: Optional training metadata dict

        Returns:
            True if save succeeded
        """
        try:
            model_bytes = pickle.dumps(model)
            self._cache.set(key, model_bytes.hex(), constants.ML_MODEL_TTL)

            if metadata:
                meta_key = f"{key}:meta"
                self._cache.set(
                    meta_key,
                    json.dumps(metadata),
                    constants.ML_MODEL_TTL,
                )

            logger.info(f"Model saved: {key} ({len(model_bytes)} bytes)")
            return True
        except Exception:
            logger.error(f"Failed to save model: {key}", exc_info=True)
            return False

    def load_model(self, key: str) -> object | None:
        """Deserialize a LightGBM model from Redis.

        Args:
            key: Redis key for the model

        Returns:
            The deserialized model, or None if not found
        """
        try:
            raw = self._cache.get(key)
            if raw is None:
                return None
            return pickle.loads(bytes.fromhex(raw))
        except Exception:
            logger.error(f"Failed to load model: {key}", exc_info=True)
            return None

    def get_metadata(self, key: str) -> dict | None:
        """Get model metadata.

        Args:
            key: Redis key for the model

        Returns:
            Metadata dict, or None if not found
        """
        try:
            raw = self._cache.get(f"{key}:meta")
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            return None

    def save_feature_names(self, names: list[str]) -> None:
        """Store canonical feature name ordering."""
        self._cache.set(
            constants.ML_FEATURE_NAMES_KEY,
            json.dumps(names),
            constants.ML_MODEL_TTL,
        )

    def load_feature_names(self) -> list[str] | None:
        """Load canonical feature name ordering."""
        raw = self._cache.get(constants.ML_FEATURE_NAMES_KEY)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def models_available(self) -> bool:
        """Check if all three models are present in Redis."""
        for key in [
            constants.ML_DIRECTION_MODEL_KEY,
            constants.ML_QUANTILE_LOW_KEY,
            constants.ML_QUANTILE_HIGH_KEY,
        ]:
            if self._cache.get(key) is None:
                return False
        return True

    def get_status(self) -> dict:
        """Get model training status and metadata."""
        status = {
            "models_available": self.models_available(),
            "direction_model": self.get_metadata(constants.ML_DIRECTION_MODEL_KEY),
            "quantile_low_model": self.get_metadata(constants.ML_QUANTILE_LOW_KEY),
            "quantile_high_model": self.get_metadata(constants.ML_QUANTILE_HIGH_KEY),
        }
        train_status = self._cache.get(constants.ML_TRAIN_STATUS_KEY)
        status["last_train_status"] = train_status
        return status

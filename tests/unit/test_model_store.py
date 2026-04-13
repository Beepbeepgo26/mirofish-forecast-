"""Test ModelStore."""

import pickle
from unittest.mock import MagicMock, patch

import pytest

from mirofish_forecast.data.cache import CacheClient
from mirofish_forecast.ml.model_store import ModelStore


@pytest.fixture
def store(mock_cache: MagicMock):
    """ModelStore with mocked cache."""
    with patch.object(CacheClient, "__init__", lambda self, s: None):
        s = ModelStore.__new__(ModelStore)
        s._cache = mock_cache
        return s


class TestModelStore:
    def test_save_and_load_roundtrip(self, store: ModelStore, mock_cache: MagicMock) -> None:
        """save_model + load_model should round-trip an object."""
        obj = {"type": "test_model", "params": [1, 2, 3]}
        store.save_model("test_key", obj, {"accuracy": 0.95})
        assert mock_cache.set.called

        # Simulate what Redis would return
        saved_hex = mock_cache.set.call_args_list[0][0][1]
        mock_cache.get.return_value = saved_hex

        loaded = store.load_model("test_key")
        assert loaded == obj

    def test_models_available_false_when_empty(
        self, store: ModelStore, mock_cache: MagicMock
    ) -> None:
        """Should return False when no models in Redis."""
        mock_cache.get.return_value = None
        assert store.models_available() is False

    def test_models_available_true(self, store: ModelStore, mock_cache: MagicMock) -> None:
        """Should return True when all three models present."""
        fake = pickle.dumps({"model": True}).hex()
        mock_cache.get.return_value = fake
        assert store.models_available() is True

    def test_get_metadata(self, store: ModelStore, mock_cache: MagicMock) -> None:
        """Should return parsed metadata."""
        import json

        meta = {"trained_at": "2026-01-01", "accuracy": 0.85}
        mock_cache.get.return_value = json.dumps(meta)
        result = store.get_metadata("test_key")
        assert result == meta

    def test_get_status(self, store: ModelStore, mock_cache: MagicMock) -> None:
        """get_status should return a dict with models_available."""
        mock_cache.get.return_value = None
        status = store.get_status()
        assert "models_available" in status
        assert "last_train_status" in status

"""Test SyntheticBootstrapper."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mirofish_forecast.calibration.bootstrap import SyntheticBootstrapper
from mirofish_forecast.data.cache import CacheClient


@pytest.fixture
def _patch_cache(mock_cache: MagicMock):
    """Patch CacheClient constructor to return the mock_cache fixture."""
    with patch.object(CacheClient, "__init__", lambda self, s: None):
        with patch.object(CacheClient, "get", mock_cache.get):
            with patch.object(CacheClient, "set", mock_cache.set):
                with patch.object(CacheClient, "delete", mock_cache.delete):
                    yield mock_cache


class TestSyntheticBootstrapper:
    def test_skips_if_already_complete(
        self,
        mock_settings,
        mock_cache: MagicMock,
        _patch_cache,
    ) -> None:
        """Should skip if bootstrap already ran."""
        mock_cache.get.return_value = "complete"
        bootstrapper = SyntheticBootstrapper(mock_settings)
        result = bootstrapper.run()
        assert result["generated"] == 0
        assert "already complete" in result["message"]

    def test_generates_samples(
        self,
        mock_settings,
        mock_cache: MagicMock,
        _patch_cache,
    ) -> None:
        """Should generate synthetic samples from historical data."""
        mock_cache.get.return_value = None

        fake_closes = np.linspace(5200, 5600, 2000)
        with patch.object(
            SyntheticBootstrapper,
            "_fetch_historical",
            return_value=fake_closes,
        ):
            bootstrapper = SyntheticBootstrapper(mock_settings)
            result = bootstrapper.run()

        assert result["generated"] > 0
        # Should have called cache.set for records + index + status
        assert mock_cache.set.call_count > result["generated"]

    def test_reset_clears_status(
        self,
        mock_settings,
        mock_cache: MagicMock,
        _patch_cache,
    ) -> None:
        """Should clear the bootstrap status key."""
        bootstrapper = SyntheticBootstrapper(mock_settings)
        bootstrapper.reset()
        mock_cache.delete.assert_called()

    def test_get_status(
        self,
        mock_settings,
        mock_cache: MagicMock,
        _patch_cache,
    ) -> None:
        """Should return current status."""
        mock_cache.get.return_value = "complete"
        bootstrapper = SyntheticBootstrapper(mock_settings)
        assert bootstrapper.get_status() == "complete"

    def test_handles_insufficient_data(
        self,
        mock_settings,
        mock_cache: MagicMock,
        _patch_cache,
    ) -> None:
        """Should handle case where historical data is too short."""
        mock_cache.get.return_value = None
        with patch.object(
            SyntheticBootstrapper,
            "_fetch_historical",
            return_value=np.array([5400.0] * 50),
        ):
            bootstrapper = SyntheticBootstrapper(mock_settings)
            result = bootstrapper.run()
        assert "generated" in result

    def test_idempotent_second_run(
        self,
        mock_settings,
        mock_cache: MagicMock,
        _patch_cache,
    ) -> None:
        """Second run should be a no-op after the first completes."""
        call_count = 0

        def mock_get(key):
            nonlocal call_count
            call_count += 1
            # First call returns None (not yet run),
            # subsequent calls return "complete"
            if call_count == 1:
                return None
            return "complete"

        mock_cache.get.side_effect = mock_get

        fake_closes = np.linspace(5200, 5600, 2000)
        with patch.object(
            SyntheticBootstrapper,
            "_fetch_historical",
            return_value=fake_closes,
        ):
            bootstrapper = SyntheticBootstrapper(mock_settings)
            result1 = bootstrapper.run()
            assert result1["generated"] > 0

            # Reset side_effect to always return "complete"
            mock_cache.get.side_effect = None
            mock_cache.get.return_value = "complete"
            result2 = bootstrapper.run()
            assert result2["generated"] == 0

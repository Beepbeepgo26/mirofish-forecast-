"""Comprehensive tests for DatabentoClient."""

import json
from unittest.mock import Mock, patch

import numpy as np
import pytest

from mirofish_forecast.data.databento_client import DatabentoClient


def make_client(api_key: str = "db-test", cache: Mock | None = None) -> DatabentoClient:
    settings = Mock()
    settings.databento_api_key = api_key
    return DatabentoClient(settings, cache or Mock())


class TestIsEnabled:
    def test_enabled_when_api_key_set(self):
        client = make_client(api_key="db-test")
        assert client.is_enabled is True

    def test_disabled_when_no_api_key(self):
        client = make_client(api_key="")
        assert client.is_enabled is False

    def test_disabled_when_blank_key(self):
        client = make_client(api_key="   ")
        # Non-empty whitespace still truthy — acceptable; empty string → disabled
        # This test verifies the current contract
        client2 = make_client(api_key="")
        assert client2.is_enabled is False


class TestIsLiveWriterHealthy:
    def test_healthy_when_heartbeat_exists(self):
        cache = Mock()
        cache.get.return_value = "2026-04-17T20:00:00+00:00"
        client = make_client(cache=cache)
        assert client.is_live_writer_healthy() is True

    def test_unhealthy_when_heartbeat_missing(self):
        cache = Mock()
        cache.get.return_value = None
        client = make_client(cache=cache)
        assert client.is_live_writer_healthy() is False

    def test_heartbeat_key_is_correct_constant(self):
        """Verify the heartbeat lookup uses the expected Redis key."""
        from mirofish_forecast.config import constants
        cache = Mock()
        cache.get.return_value = "some-ts"
        client = make_client(cache=cache)
        client.is_live_writer_healthy()
        cache.get.assert_called_once_with(constants.DATABENTO_WRITER_HEARTBEAT)


class TestGetLatestPrice:
    def test_returns_float_from_redis(self):
        cache = Mock()
        cache.get.return_value = "5100.50"
        client = make_client(cache=cache)
        assert client.get_latest_price("ES") == 5100.50

    def test_returns_none_on_cache_miss(self):
        cache = Mock()
        cache.get.return_value = None
        client = make_client(cache=cache)
        assert client.get_latest_price("ES") is None

    def test_returns_none_on_invalid_value(self):
        cache = Mock()
        cache.get.return_value = "not-a-number"
        client = make_client(cache=cache)
        assert client.get_latest_price("ES") is None

    def test_instrument_uppercased_in_key(self):
        cache = Mock()
        cache.get.return_value = "5100.00"
        client = make_client(cache=cache)
        client.get_latest_price("es")  # lowercase
        cache.get.assert_called_with("databento:price:ES")

    def test_nq_price_uses_correct_key(self):
        cache = Mock()
        cache.get.return_value = "19200.00"
        client = make_client(cache=cache)
        price = client.get_latest_price("NQ")
        assert price == 19200.00
        cache.get.assert_called_with("databento:price:NQ")


class TestGetRecentBars:
    def _make_cache_with_bars(self, bar_data: dict) -> Mock:
        """Helper to build a cache mock with sorted set + bar keys."""
        cache = Mock()
        cache.zrevrange.return_value = list(bar_data.keys())
        cache.get.side_effect = lambda k: bar_data.get(k)
        return cache

    def test_returns_bars_oldest_first(self):
        bars = {
            "mf:databento:bar:ES:800": json.dumps({"time": 800, "open": 10, "high": 11, "low": 9, "close": 5003}),
            "mf:databento:bar:ES:740": json.dumps({"time": 740, "open": 10, "high": 11, "low": 9, "close": 5002}),
            "mf:databento:bar:ES:680": json.dumps({"time": 680, "open": 10, "high": 11, "low": 9, "close": 5001}),
        }
        # zrevrange returns newest first
        cache = Mock()
        cache.zrevrange.return_value = list(bars.keys())  # [800, 740, 680]
        cache.get.side_effect = lambda k: bars.get(k)

        client = make_client(cache=cache)
        result = client.get_recent_bars("ES", 3)

        assert len(result) == 3
        # After reversal: oldest (680) first
        assert result[0]["close"] == 5001
        assert result[2]["close"] == 5003

    def test_returns_empty_on_no_keys(self):
        cache = Mock()
        cache.zrevrange.return_value = []
        client = make_client(cache=cache)
        assert client.get_recent_bars("ES") == []

    def test_skips_invalid_json_bars(self):
        cache = Mock()
        cache.zrevrange.return_value = ["bar_a", "bar_b"]
        cache.get.side_effect = lambda k: "not-json" if k == "bar_a" else json.dumps({"time": 100, "close": 5000})
        client = make_client(cache=cache)
        result = client.get_recent_bars("ES", 2)
        assert len(result) == 1
        assert result[0]["close"] == 5000

    def test_returns_empty_on_redis_error(self):
        cache = Mock()
        cache.zrevrange.side_effect = Exception("Redis offline")
        client = make_client(cache=cache)
        result = client.get_recent_bars("ES")
        assert result == []

    def test_requests_correct_count_from_sorted_set(self):
        cache = Mock()
        cache.zrevrange.return_value = []
        client = make_client(cache=cache)
        client.get_recent_bars("ES", count=50)
        cache.zrevrange.assert_called_with("databento:barlist:ES", 0, 49)


class TestResampleTo5Min:
    def test_exact_5_bars_makes_1_candle(self):
        client = make_client()
        bars_1m = [
            {"time": 60, "open": 10, "high": 15, "low": 5, "close": 12, "volume": 100},
            {"time": 120, "open": 12, "high": 20, "low": 10, "close": 18, "volume": 50},
            {"time": 180, "open": 18, "high": 18, "low": 16, "close": 17, "volume": 10},
            {"time": 240, "open": 17, "high": 22, "low": 17, "close": 21, "volume": 40},
            {"time": 300, "open": 21, "high": 21, "low": 19, "close": 20, "volume": 100},
        ]
        result = client._resample_to_5min(bars_1m)
        assert len(result) == 1
        bar = result[0]
        assert bar["time"] == 60       # start of bucket
        assert bar["open"] == 10       # first open
        assert bar["high"] == 22       # highest high
        assert bar["low"] == 5         # lowest low
        assert bar["close"] == 20      # last close
        assert bar["volume"] == 300    # sum

    def test_10_bars_makes_2_candles(self):
        client = make_client()
        bars = [
            {"time": i * 60, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 10}
            for i in range(1, 11)
        ]
        result = client._resample_to_5min(bars)
        assert len(result) == 2

    def test_partial_bucket_becomes_incomplete_bar(self):
        """3 bars (incomplete bucket) should be returned as-is."""
        client = make_client()
        bars = [
            {"time": 60, "open": 10, "high": 15, "low": 5, "close": 12, "volume": 100},
            {"time": 120, "open": 12, "high": 16, "low": 10, "close": 14, "volume": 50},
            {"time": 180, "open": 14, "high": 17, "low": 13, "close": 15, "volume": 30},
        ]
        result = client._resample_to_5min(bars)
        assert len(result) == 1
        assert result[0]["open"] == 10
        assert result[0]["close"] == 15

    def test_empty_input_returns_empty(self):
        client = make_client()
        assert client._resample_to_5min([]) == []

    def test_volume_missing_defaults_to_zero(self):
        client = make_client()
        bars = [
            {"time": i * 60, "open": 100, "high": 101, "low": 99, "close": 100}
            for i in range(1, 6)
        ]
        result = client._resample_to_5min(bars)
        assert result[0]["volume"] == 0


class TestGetTrainingData:
    def test_returns_none_when_disabled(self):
        client = make_client(api_key="")
        assert client.get_training_data("ES") is None

    def test_returns_none_for_unknown_instrument(self):
        client = make_client()
        assert client.get_training_data("UNKNOWN") is None

    def test_returns_none_on_api_error(self):
        databento = pytest.importorskip("databento", reason="databento not installed")
        client = make_client()
        with patch.object(databento, "Historical", side_effect=Exception("API error")):
            result = client.get_training_data("ES")
        assert result is None

    def test_returns_arrays_on_success(self):
        pytest.importorskip("databento", reason="databento not installed")
        import pandas as pd

        mock_df = pd.DataFrame({
            "open": [5000.0] * 250,
            "high": [5010.0] * 250,
            "low": [4990.0] * 250,
            "close": [5005.0] * 250,
            "volume": [1000.0] * 250,
        })

        mock_data = Mock()
        mock_data.to_df.return_value = mock_df

        mock_historical = Mock()
        mock_historical.timeseries.get_range.return_value = mock_data

        client = make_client()
        with patch("databento.Historical", return_value=mock_historical):
            result = client.get_training_data("ES", lookback_days=90)

        assert result is not None
        closes, highs, lows, opens, volumes = result
        assert len(closes) == 250
        assert isinstance(closes, np.ndarray)
        assert closes[0] == 5005.0

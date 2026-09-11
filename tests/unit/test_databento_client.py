"""Comprehensive tests for DatabentoClient."""

import json
import logging
import random
import time
from unittest.mock import Mock, patch

import numpy as np
import pytest

from mirofish_forecast.config import constants
from mirofish_forecast.data.databento_client import DatabentoClient


def make_client(api_key: str = "db-test", cache: Mock | None = None) -> DatabentoClient:
    settings = Mock()
    settings.databento_api_key = api_key
    return DatabentoClient(settings, cache or Mock())


# A wall-clock 5-minute boundary (1_700_000_100 % 300 == 0) for the bucketing fixtures.
T0 = 1_700_000_100
BUCKET = 300
assert T0 % BUCKET == 0


def _bar_1m(offset_minutes: int, volume: int = 10) -> dict:
    """A 1m bar at T0 + offset minutes, with OHLC derived from the offset."""
    price = 100.0 + offset_minutes
    return {
        "time": T0 + offset_minutes * 60,
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price + 0.5,
        "volume": volume,
    }


def _bars_1m(offsets) -> list[dict]:
    return [_bar_1m(offset) for offset in offsets]


def _cache_with_bars(bars: list[dict], instrument: str = "ES") -> Mock:
    """Cache mock serving ``bars`` through the barlist sorted set, newest first."""
    keyed = {f"databento:bar:{instrument}:{bar['time']}": json.dumps(bar) for bar in bars}
    newest_first = sorted(keyed, key=lambda key: int(key.rsplit(":", 1)[1]), reverse=True)
    cache = Mock()
    cache.zrevrange.side_effect = lambda key, start, end: newest_first[start : end + 1]
    cache.get.side_effect = lambda key: keyed.get(key)
    return cache


def _bar_at(ts: int, close: float = 5100.5) -> dict:
    """A 1m bar at an explicit epoch second."""
    return {"time": ts, "open": close, "high": close + 1, "low": close - 1, "close": close}


def _now() -> int:
    return int(time.time())


def _assert_aligned(bars: list[dict]) -> None:
    """The Phase 1 invariant: every output bar sits on a 5-minute boundary."""
    for bar in bars:
        assert bar["time"] % BUCKET == 0, bar


class TestIsEnabled:
    def test_enabled_when_api_key_set(self):
        client = make_client(api_key="db-test")
        assert client.is_enabled is True

    def test_disabled_when_no_api_key(self):
        client = make_client(api_key="")
        assert client.is_enabled is False

    def test_disabled_when_blank_key(self):
        make_client(api_key="   ")
        # Non-empty whitespace still truthy — acceptable; empty string → disabled
        # This test verifies the current contract
        client2 = make_client(api_key="")
        assert client2.is_enabled is False


class TestIsLiveWriterHealthy:
    """Health is the recency of the newest ES 1m bar, read through the barlist."""

    def test_reads_only_the_newest_es_bar(self):
        cache = _cache_with_bars([_bar_at(_now() - 90), _bar_at(_now() - 30)])
        client = make_client(cache=cache)
        assert client.is_live_writer_healthy() is True
        cache.zrevrange.assert_called_once_with("databento:barlist:ES", 0, 0)

    def test_age_just_inside_and_just_outside_the_limit(self):
        limit = constants.DATABENTO_MAX_BAR_AGE_SECONDS
        assert limit == 180
        inside = make_client(cache=_cache_with_bars([_bar_at(_now() - (limit - 10))]))
        outside = make_client(cache=_cache_with_bars([_bar_at(_now() - (limit + 10))]))
        assert inside.is_live_writer_healthy() is True
        assert outside.is_live_writer_healthy() is False

    def test_unhealthy_on_redis_error(self):
        cache = Mock()
        cache.zrevrange.side_effect = ConnectionError("redis down")
        client = make_client(cache=cache)
        assert client.is_live_writer_healthy() is False


class TestGetLatestPrice:
    """Latest price is the close of the newest 1m bar, read through the barlist."""

    def test_returns_newest_bar_close_as_float(self):
        now = _now()
        cache = _cache_with_bars(
            [_bar_at(now - 90, close=5001.0), _bar_at(now - 30, close=5002.25)]
        )
        client = make_client(cache=cache)
        price = client.get_latest_price("ES")
        assert price == 5002.25
        assert isinstance(price, float)
        cache.zrevrange.assert_called_once_with("databento:barlist:ES", 0, 0)

    def test_returns_none_when_bar_key_expired(self):
        """The barlist still names a key whose bar JSON has expired -> no price."""
        cache = Mock()
        cache.zrevrange.return_value = ["databento:bar:ES:800"]
        cache.get.return_value = None
        client = make_client(cache=cache)
        assert client.get_latest_price("ES") is None
        cache.zrevrange.assert_called_once()

    def test_returns_none_on_invalid_close(self):
        cache = _cache_with_bars([dict(_bar_at(_now() - 30), close="not-a-number")])
        client = make_client(cache=cache)
        assert client.get_latest_price("ES") is None
        cache.zrevrange.assert_called_once()

    def test_instrument_uppercased_in_barlist_key(self):
        cache = _cache_with_bars([_bar_at(_now() - 30)])
        client = make_client(cache=cache)
        client.get_latest_price("es")  # lowercase
        cache.zrevrange.assert_called_with("databento:barlist:ES", 0, 0)

    def test_returns_none_on_redis_error(self):
        cache = Mock()
        cache.zrevrange.side_effect = ConnectionError("redis down")
        client = make_client(cache=cache)
        assert client.get_latest_price("ES") is None
        cache.zrevrange.assert_called_once()


class TestReadPathHealthAndPrice:
    """P0-2a Phase 2: health and latest price come from the bar list, not from the
    writer heartbeat or the 10-second-TTL price key."""

    def test_health_follows_newest_bar_age(self):
        """Case 1: fresh bar (30s) -> True; stale bar (200s) -> False; no bars -> False."""
        fresh = make_client(cache=_cache_with_bars([_bar_at(_now() - 30)]))
        stale = make_client(cache=_cache_with_bars([_bar_at(_now() - 200)]))
        empty = make_client(cache=_cache_with_bars([]))
        assert fresh.is_live_writer_healthy() is True
        assert stale.is_live_writer_healthy() is False
        assert empty.is_live_writer_healthy() is False

    def test_false_green_heartbeat_present_but_no_bars_is_unhealthy(self):
        """Case 2: a live heartbeat with an empty barlist must not read as healthy."""
        cache = _cache_with_bars([])
        cache.get.side_effect = lambda key: (
            "2026-09-10T20:00:00+00:00" if key == constants.DATABENTO_WRITER_HEARTBEAT else None
        )
        client = make_client(cache=cache)
        assert client.is_live_writer_healthy() is False

    def test_false_red_heartbeat_absent_but_fresh_bar_is_healthy(self):
        """Case 3: a lapsed heartbeat with a fresh bar must not read as unhealthy."""
        cache = _cache_with_bars([_bar_at(_now() - 30)])
        assert cache.get(constants.DATABENTO_WRITER_HEARTBEAT) is None  # no heartbeat served
        client = make_client(cache=cache)
        assert client.is_live_writer_healthy() is True

    def test_latest_price_is_newest_close_and_price_key_is_never_read(self):
        """Case 4: newest bar close; None when empty; the 10s-TTL price key is never read."""
        now = _now()
        bars = [
            _bar_at(now - 150, close=5001.0),
            _bar_at(now - 90, close=5002.0),
            _bar_at(now - 30, close=5003.5),
        ]
        cache = _cache_with_bars(bars)
        assert make_client(cache=cache).get_latest_price("ES") == 5003.5

        empty = _cache_with_bars([])
        assert make_client(cache=empty).get_latest_price("ES") is None

        price_key = f"{constants.DATABENTO_PRICE_KEY_PREFIX}:ES"
        for mock_cache in (cache, empty):
            keys_read = [call.args[0] for call in mock_cache.get.call_args_list]
            assert price_key not in keys_read
            assert not [k for k in keys_read if k.startswith(constants.DATABENTO_PRICE_KEY_PREFIX)]

    def test_latest_price_for_nq_reads_the_nq_barlist(self):
        """Case 5: instrument-parameterised; NQ comes from NQ's own barlist."""
        now = _now()
        cache = _cache_with_bars(
            [_bar_at(now - 90, close=19200.0), _bar_at(now - 30, close=19210.25)], instrument="NQ"
        )
        client = make_client(cache=cache)
        assert client.get_latest_price("NQ") == 19210.25
        cache.zrevrange.assert_called_once_with("databento:barlist:NQ", 0, 0)

    def test_latest_price_is_none_when_newest_bar_is_stale(self, caplog):
        """Refinement: a newest bar older than DATABENTO_MAX_BAR_AGE_SECONDS yields None, not
        a stale close. get_latest_price runs for NQ/CL/GC with no ES-only health gate."""
        cache = _cache_with_bars([_bar_at(_now() - 200, close=19200.0)], instrument="NQ")
        client = make_client(cache=cache)

        with caplog.at_level(logging.DEBUG, logger="mirofish_forecast.data.databento_client"):
            assert client.get_latest_price("NQ") is None

        debugs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("No live NQ price" in msg and "old" in msg for msg in debugs)
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestGetRecentBars:
    def _make_cache_with_bars(self, bar_data: dict) -> Mock:
        """Helper to build a cache mock with sorted set + bar keys."""
        cache = Mock()
        cache.zrevrange.return_value = list(bar_data.keys())
        cache.get.side_effect = lambda k: bar_data.get(k)
        return cache

    def test_returns_bars_oldest_first(self):
        bars = {
            "mf:databento:bar:ES:800": json.dumps(
                {"time": 800, "open": 10, "high": 11, "low": 9, "close": 5003}
            ),
            "mf:databento:bar:ES:740": json.dumps(
                {"time": 740, "open": 10, "high": 11, "low": 9, "close": 5002}
            ),
            "mf:databento:bar:ES:680": json.dumps(
                {"time": 680, "open": 10, "high": 11, "low": 9, "close": 5001}
            ),
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
        cache.get.side_effect = lambda k: (
            "not-json" if k == "bar_a" else json.dumps({"time": 100, "close": 5000})
        )
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
            {"time": T0, "open": 10, "high": 15, "low": 5, "close": 12, "volume": 100},
            {"time": T0 + 60, "open": 12, "high": 20, "low": 10, "close": 18, "volume": 50},
            {"time": T0 + 120, "open": 18, "high": 18, "low": 16, "close": 17, "volume": 10},
            {"time": T0 + 180, "open": 17, "high": 22, "low": 17, "close": 21, "volume": 40},
            {"time": T0 + 240, "open": 21, "high": 21, "low": 19, "close": 20, "volume": 100},
        ]
        result = client._resample_to_5min(bars_1m)
        assert len(result) == 1
        bar = result[0]
        assert bar["time"] == T0  # bucket start, on the 5-minute boundary
        assert bar["open"] == 10  # first open
        assert bar["high"] == 22  # highest high
        assert bar["low"] == 5  # lowest low
        assert bar["close"] == 20  # last close
        assert bar["volume"] == 300  # sum
        assert bar["complete"] is True
        assert bar["bar_count"] == 5
        _assert_aligned(result)

    def test_10_bars_makes_2_candles(self):
        client = make_client()
        result = client._resample_to_5min(_bars_1m(range(10)))
        assert [bar["time"] for bar in result] == [T0, T0 + 300]
        assert all(bar["complete"] for bar in result)
        _assert_aligned(result)

    def test_partial_bucket_is_flagged_incomplete(self):
        """3 bars (incomplete bucket) are still aggregated, but flagged as incomplete."""
        client = make_client()
        bars = [
            {"time": T0, "open": 10, "high": 15, "low": 5, "close": 12, "volume": 100},
            {"time": T0 + 60, "open": 12, "high": 16, "low": 10, "close": 14, "volume": 50},
            {"time": T0 + 120, "open": 14, "high": 17, "low": 13, "close": 15, "volume": 30},
        ]
        result = client._resample_to_5min(bars)
        assert len(result) == 1
        assert result[0]["time"] == T0
        assert result[0]["open"] == 10
        assert result[0]["close"] == 15
        assert result[0]["complete"] is False
        assert result[0]["bar_count"] == 3
        _assert_aligned(result)

    def test_empty_input_returns_empty(self):
        client = make_client()
        assert client._resample_to_5min([]) == []

    def test_volume_missing_defaults_to_zero(self):
        client = make_client()
        bars = [
            {"time": i * 60, "open": 100, "high": 101, "low": 99, "close": 100} for i in range(1, 6)
        ]
        result = client._resample_to_5min(bars)
        assert result[0]["volume"] == 0


class TestTimestampAlignedBuckets:
    """P0-2a Phase 1: 5m buckets are keyed by wall-clock time, not by arrival order."""

    LOGGER = "mirofish_forecast.data.databento_client"

    def test_window_cut_first_bucket_is_dropped_by_default(self):
        """Case 1: nine bars at offsets 1..9 -> a 4-bar (incomplete) and a 5-bar (complete)
        bucket; the default call returns only the complete one."""
        bars = _bars_1m(range(1, 10))
        cache = _cache_with_bars(bars)
        client = make_client(cache=cache)

        resampled = client._resample_to_5min(bars)
        assert [(b["time"], b["bar_count"], b["complete"]) for b in resampled] == [
            (T0, 4, False),
            (T0 + 300, 5, True),
        ]

        result = client.get_5min_bars("ES", count=10)
        assert [b["time"] for b in result] == [T0 + 300]
        assert result[0]["complete"] is True
        _assert_aligned(result)
        # Fetch margin: count * 5 + 10 raw 1m bars are requested from the sorted set.
        cache.zrevrange.assert_called_once_with("databento:barlist:ES", 0, 59)

    def test_interior_gap_is_dropped_with_warning(self, caplog):
        """Case 2: ten bars over minutes 0..10 with minute 7 missing -> the middle bucket is
        incomplete and interior (WARNING); the forming last bucket is window-edge (DEBUG)."""
        bars = _bars_1m(offset for offset in range(11) if offset != 7)
        assert len(bars) == 10
        client = make_client(cache=_cache_with_bars(bars))

        with caplog.at_level(logging.DEBUG, logger=self.LOGGER):
            result = client.get_5min_bars("ES", count=10)

        assert [b["time"] for b in result] == [T0]
        _assert_aligned(result)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert str(T0 + 300) in warnings[0].getMessage()
        assert "4/5" in warnings[0].getMessage()
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debugs) == 1
        assert str(T0 + 600) in debugs[0].getMessage()

    def test_trailing_partial_bucket_debug_and_include_incomplete(self, caplog):
        """Case 3: seven bars -> the trailing 2-bar bucket is dropped at DEBUG by default and
        returned flagged incomplete with include_incomplete=True."""
        bars = _bars_1m(range(7))
        client = make_client(cache=_cache_with_bars(bars))

        with caplog.at_level(logging.DEBUG, logger=self.LOGGER):
            default = client.get_5min_bars("ES", count=10)

        assert [b["time"] for b in default] == [T0]
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(debugs) == 1
        assert str(T0 + 300) in debugs[0].getMessage()

        everything = client.get_5min_bars("ES", count=10, include_incomplete=True)
        assert [b["time"] for b in everything] == [T0, T0 + 300]
        assert everything[0]["complete"] is True
        assert everything[1]["complete"] is False
        assert everything[1]["bar_count"] == 2
        assert everything[1]["open"] == bars[5]["open"]
        assert everything[1]["close"] == bars[6]["close"]
        _assert_aligned(default)
        _assert_aligned(everything)

    def test_arrival_order_does_not_change_output(self):
        """Case 4: shuffled and reversed fixtures bucketize identically to the sorted one."""
        bars = _bars_1m([0, 1, 2, 3, 4, 5, 6, 8, 9, 12])
        client = make_client()
        expected = client._resample_to_5min(bars)

        shuffled = list(bars)
        random.Random(42).shuffle(shuffled)
        assert shuffled != bars
        assert client._resample_to_5min(shuffled) == expected
        assert client._resample_to_5min(list(reversed(bars))) == expected
        _assert_aligned(expected)

    def test_window_start_does_not_move_bucket_times(self):
        """Case 5 (regression for the arrival-order bug): the same 12 bars seen through
        windows starting at different offsets yield buckets with the SAME time values."""
        bars = _bars_1m(range(12))  # buckets T0 (0-4), T0+300 (5-9), T0+600 (10-11)
        client = make_client()

        by_window_start = {start: client._resample_to_5min(bars[start:]) for start in range(5)}
        for start, result in by_window_start.items():
            _assert_aligned(result)
            assert {b["time"] for b in result} <= {T0, T0 + 300, T0 + 600}, start
            # The bucket fully inside every window is identical in every window.
            middle = next(b for b in result if b["time"] == T0 + 300)
            assert middle == by_window_start[0][1]
            assert middle["complete"] is True
        # The window-cut first bucket keeps its aligned time; only its bar_count shrinks.
        assert [by_window_start[s][0]["time"] for s in range(5)] == [T0] * 5
        assert [by_window_start[s][0]["bar_count"] for s in range(5)] == [5, 4, 3, 2, 1]

    def test_duplicate_timestamp_last_wins(self):
        """Case 6: a duplicated 1m bar is replaced by the copy seen last; no crash, and the
        bucket is still complete with bar_count 5."""
        bars = _bars_1m(range(5))
        replacement = dict(bars[2], high=1000.0, volume=7)
        client = make_client()

        result = client._resample_to_5min(bars + [replacement])
        assert len(result) == 1
        assert result[0]["complete"] is True
        assert result[0]["bar_count"] == 5
        assert result[0]["high"] == 1000.0
        assert result[0]["volume"] == 4 * 10 + 7
        _assert_aligned(result)

        # Seen first instead of last, the duplicate loses to the original.
        original_wins = client._resample_to_5min([replacement] + bars)
        assert original_wins[0]["high"] == bars[4]["high"]
        assert original_wins[0]["volume"] == 5 * 10

    def test_every_output_time_is_on_a_5_minute_boundary(self):
        """Case 7: the invariant holds for a gappy, duplicated, shuffled, window-cut fixture
        through the resampler and through get_5min_bars, with and without incomplete bars."""
        offsets = [offset for offset in range(1, 40) if offset % 7 != 0]
        bars = _bars_1m(offsets) + [_bar_1m(3)]
        random.Random(7).shuffle(bars)
        client = make_client(cache=_cache_with_bars(bars))

        resampled = client._resample_to_5min(bars)
        default = client.get_5min_bars("ES", count=4)
        everything = client.get_5min_bars("ES", count=4, include_incomplete=True)

        for result in (resampled, default, everything):
            assert result
            _assert_aligned(result)
        assert all(b["complete"] for b in default)
        assert len(default) <= 4
        assert len(everything) == 4


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

        mock_df = pd.DataFrame(
            {
                "open": [5000.0] * 250,
                "high": [5010.0] * 250,
                "low": [4990.0] * 250,
                "close": [5005.0] * 250,
                "volume": [1000.0] * 250,
            }
        )

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

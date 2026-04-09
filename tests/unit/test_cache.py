from unittest.mock import patch

from mirofish_forecast.data.cache import CacheClient


class TestCacheClient:
    def test_get_returns_none_on_miss(self, mock_settings):
        with patch("mirofish_forecast.data.cache.Redis") as mock_redis:
            mock_redis.return_value.get.return_value = None
            cache = CacheClient(mock_settings)
            assert cache.get("nonexistent") is None

    def test_get_returns_value_on_hit(self, mock_settings):
        with patch("mirofish_forecast.data.cache.Redis") as mock_redis:
            mock_redis.return_value.get.return_value = '{"test": true}'
            cache = CacheClient(mock_settings)
            assert cache.get("existing") == '{"test": true}'

    def test_set_does_not_raise_on_error(self, mock_settings):
        with patch("mirofish_forecast.data.cache.Redis") as mock_redis:
            mock_redis.return_value.set.side_effect = Exception("Redis down")
            cache = CacheClient(mock_settings)
            cache.set("key", "value", 60)  # Should not raise

    def test_health_check_returns_true(self, mock_settings):
        with patch("mirofish_forecast.data.cache.Redis") as mock_redis:
            mock_redis.return_value.ping.return_value = True
            cache = CacheClient(mock_settings)
            assert cache.health_check() is True

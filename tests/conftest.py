from unittest.mock import MagicMock

import pytest

from mirofish_forecast.app import create_app
from mirofish_forecast.data.cache import CacheClient


@pytest.fixture
def mock_settings(monkeypatch):
    """Provide test settings via environment variables."""
    monkeypatch.setenv("MIROFISH_FRED_API_KEY", "test_fred_key")
    monkeypatch.setenv("MIROFISH_REDIS_URL", "https://fake.upstash.io")
    monkeypatch.setenv("MIROFISH_REDIS_TOKEN", "fake_token")
    monkeypatch.setenv("MIROFISH_IB_RELAY_URL", "http://localhost:5001")
    # Clear the lru_cache so settings reload with test env vars
    from mirofish_forecast.config.settings import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def mock_cache():
    """A CacheClient that always misses (returns None for get)."""
    cache = MagicMock(spec=CacheClient)
    cache.get.return_value = None
    cache.set.return_value = None
    cache.delete.return_value = None
    cache.health_check.return_value = True
    return cache


@pytest.fixture
def app(mock_settings):
    """Flask test app."""
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()

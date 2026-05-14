"""Tests for pipeline path routing priority."""

from unittest.mock import MagicMock

from mirofish_forecast.config.settings import Settings
from mirofish_forecast.models.query import ForecastQuery, QueryType
from mirofish_forecast.services.pipeline import ForecastPipeline


def make_settings():
    return Settings(
        fast_path_enabled=True,
        fast_path_auto_route=True,
        fred_api_key="test",
        redis_url="test",
        redis_token="test",
        databento_api_key="test",
        openai_api_key="test",
    )


def test_deep_preset_forces_full_path():
    """Deep tier must use full MC path even for directional queries."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Is ES going up?",
        instrument="ES",
        query_type=QueryType.DIRECTION_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="deep",
        path_override=None,
    )
    assert result is False


def test_standard_preset_forces_full_path():
    """Standard tier must use full MC path."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Is ES going up?",
        instrument="ES",
        query_type=QueryType.DIRECTION_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="standard",
        path_override=None,
    )
    assert result is False


def test_quick_preset_forces_full_path():
    """Quick tier must use full MC path."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Is ES going up?",
        instrument="ES",
        query_type=QueryType.DIRECTION_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="quick",
        path_override=None,
    )
    assert result is False


def test_simple_preset_forces_fast_path():
    """Simple tier uses fast path."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Where will ES be?",
        instrument="ES",
        query_type=QueryType.RANGE_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="simple",
        path_override=None,
    )
    assert result is True


def test_explicit_path_override_beats_preset():
    """Explicit path='fast' overrides Deep preset."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Where will ES be?",
        instrument="ES",
        query_type=QueryType.RANGE_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="deep",
        path_override="fast",
    )
    assert result is True


def test_auto_route_only_without_preset():
    """Auto-routing only applies when no preset is given."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Is ES going up?",
        instrument="ES",
        query_type=QueryType.DIRECTION_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="none",  # Not a recognized sim_preset
        path_override=None,
    )
    assert result is True  # Auto-routes to fast for directional


def test_auto_route_full_for_distribution():
    """Distribution queries auto-route to full when no preset."""
    settings = make_settings()
    pipeline = ForecastPipeline(settings, MagicMock())
    query = ForecastQuery(
        raw_query="Where will ES be?",
        instrument="ES",
        query_type=QueryType.RANGE_FORECAST,
        forecast_horizon_minutes=60,
    )
    result = pipeline._should_use_fast_path(
        query=query,
        sim_preset="none",
        path_override=None,
    )
    assert result is False

"""Unit tests for Brooks per-agent retrieval orchestration."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from mirofish_forecast.brooks.agent_retrieval import (
    AGENT_FILTERS,
    _apply_diversity_cap,
    retrieve_agent_analogs,
)
from mirofish_forecast.models.brooks import BrooksAnalog


def _make_analog(
    page: int = 1,
    pattern_type: str = "bull_flag",
    score: float = 0.9,
) -> BrooksAnalog:
    return BrooksAnalog(
        page_number=page,
        pattern_type=pattern_type,
        direction="long",
        outcome="success",
        probability="high",
        always_in_direction="AIL",
        day_type="trend",
        brooks_concepts=["AIL"],
        similarity_score=score,
        gcs_jpg_path="gs://bucket/page.jpg",
        analysis_summary="Test analysis.",
    )


class TestDiversityCap:
    def test_limits_per_pattern_type(self) -> None:
        candidates = [_make_analog(i, "A") for i in range(10)] + [
            _make_analog(i + 10, "B") for i in range(10)
        ]
        result = _apply_diversity_cap(candidates, top_k=5, max_per_pattern=2)
        a_count = sum(1 for r in result if r.pattern_type == "A")
        b_count = sum(1 for r in result if r.pattern_type == "B")
        assert a_count == 2
        assert b_count == 2
        assert len(result) == 4  # only 4 available under cap (2A + 2B < 5)

    def test_returns_fewer_if_not_enough_diversity(self) -> None:
        candidates = [_make_analog(i, "A") for i in range(5)]
        result = _apply_diversity_cap(candidates, top_k=5, max_per_pattern=2)
        assert len(result) == 2

    def test_multiple_pattern_types(self) -> None:
        candidates = (
            [_make_analog(i, "A", 0.95 - i * 0.01) for i in range(5)]
            + [_make_analog(i + 5, "B", 0.90 - i * 0.01) for i in range(5)]
            + [_make_analog(i + 10, "C", 0.85 - i * 0.01) for i in range(5)]
        )
        result = _apply_diversity_cap(candidates, top_k=5, max_per_pattern=2)
        assert len(result) == 5
        pattern_counts = {}
        for r in result:
            pattern_counts[r.pattern_type] = pattern_counts.get(r.pattern_type, 0) + 1
        assert all(v <= 2 for v in pattern_counts.values())


class TestRetrieveAgentAnalogs:
    def test_returns_analogs_and_telemetry(self) -> None:
        mock_vector = MagicMock()
        mock_oai = MagicMock()

        # Mock the embedding call
        mock_oai.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )

        # Mock vector query results
        r1 = MagicMock()
        r1.metadata = {
            "page_number": 1,
            "pattern_type": "bull_flag",
            "direction": "long",
            "outcome": "success",
            "probability": "high",
            "always_in_direction": "AIL",
            "day_type": "trend",
            "brooks_concepts": ["AIL"],
            "gcs_jpg_url": "gs://b/p.jpg",
        }
        r1.score = 0.92
        mock_vector.query.return_value = [r1]

        with patch(
            "mirofish_forecast.brooks.retriever._analysis_cache",
            {1: "Test summary"},
        ), patch(
            "mirofish_forecast.brooks.retriever._load_analysis_cache",
        ):
            analogs, telemetry = asyncio.run(
                retrieve_agent_analogs(
                    "institutional", "test context",
                    mock_vector, mock_oai,
                )
            )

        assert len(analogs) == 1
        assert analogs[0].pattern_type == "bull_flag"
        assert telemetry["agent_role"] == "institutional"
        assert telemetry["analogs_retrieved"] == 1
        assert telemetry["fallback_reason"] is None

    def test_precomputed_embedding_skips_openai(self) -> None:
        mock_vector = MagicMock()
        mock_oai = MagicMock()
        mock_vector.query.return_value = []

        with patch(
            "mirofish_forecast.brooks.retriever._load_analysis_cache",
        ):
            analogs, telemetry = asyncio.run(
                retrieve_agent_analogs(
                    "institutional", "test context",
                    mock_vector, mock_oai,
                    precomputed_embedding=[0.1] * 1536,
                )
            )

        mock_oai.embeddings.create.assert_not_called()
        assert telemetry["analogs_retrieved"] == 0

    def test_timeout_returns_empty_with_fallback(self) -> None:
        mock_vector = MagicMock()
        mock_oai = MagicMock()

        async def slow_query(*args, **kwargs):
            await asyncio.sleep(5)
            return []

        with patch(
            "mirofish_forecast.brooks.agent_retrieval._do_retrieval",
            side_effect=slow_query,
        ):
            analogs, telemetry = asyncio.run(
                retrieve_agent_analogs(
                    "institutional", "test context",
                    mock_vector, mock_oai,
                    timeout_seconds=0.1,
                )
            )

        assert len(analogs) == 0
        assert telemetry["fallback_reason"] == "upstash_timeout"

    def test_exception_returns_empty_with_fallback(self) -> None:
        mock_vector = MagicMock()
        mock_oai = MagicMock()

        async def failing_retrieval(*args, **kwargs):
            raise ConnectionError("Upstash unreachable")

        with patch(
            "mirofish_forecast.brooks.agent_retrieval._do_retrieval",
            side_effect=failing_retrieval,
        ):
            analogs, telemetry = asyncio.run(
                retrieve_agent_analogs(
                    "market_maker", "test context",
                    mock_vector, mock_oai,
                )
            )

        assert len(analogs) == 0
        assert telemetry["fallback_reason"] == "upstash_error"

    def test_telemetry_has_all_keys(self) -> None:
        mock_vector = MagicMock()
        mock_oai = MagicMock()
        mock_vector.query.return_value = []

        with patch(
            "mirofish_forecast.brooks.retriever._load_analysis_cache",
        ):
            _, telemetry = asyncio.run(
                retrieve_agent_analogs(
                    "retail", "test",
                    mock_vector, mock_oai,
                    precomputed_embedding=[0.1] * 1536,
                )
            )

        required_keys = {
            "agent_role", "analogs_retrieved", "fallback_reason",
            "retrieval_latency_ms", "filter_used", "pattern_types_returned",
        }
        assert required_keys == set(telemetry.keys())

    def test_uses_correct_filter_for_each_role(self) -> None:
        assert "outcome = 'success'" in AGENT_FILTERS["institutional_flow"]
        assert "pattern_type GLOB '*reversal*'" in AGENT_FILTERS["market_maker"]
        assert "pattern_type GLOB '*failed*'" in AGENT_FILTERS["retail_contrarian"]

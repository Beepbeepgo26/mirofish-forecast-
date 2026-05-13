"""Unit tests for Brooks retriever module."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mirofish_forecast.brooks.retriever import (
    _analysis_cache,
    _load_analysis_cache,
    _strip_boilerplate,
    embed_query_context,
    retrieve_analogs,
)
from mirofish_forecast.models.brooks import BrooksAnalog


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Clear the analysis cache before each test."""
    _analysis_cache.clear()


@pytest.fixture
def enriched_jsonl(tmp_path: Path) -> Path:
    """Create a temporary enriched JSONL for cache testing."""
    p = tmp_path / "enriched.jsonl"
    records = [
        {
            "page_number": 1,
            "source_jpg": "page_001.jpg",
            "pattern_type": "bull_flag",
            "direction": "long",
            "probability": "high",
            "outcome": "success",
            "always_in_direction": "AIL",
            "day_type": "trend",
            "key_levels": [],
            "brooks_concepts": ["AIL", "PB"],
            "ocr_text": "ocr",
            "analysis_text": "A" * 500,  # 500 chars, will be truncated to 400
        },
        {
            "page_number": 5,
            "source_jpg": "page_005.jpg",
            "pattern_type": "FBO",
            "direction": "short",
            "probability": "medium",
            "outcome": "trap",
            "always_in_direction": "AIS",
            "day_type": "TR",
            "key_levels": [],
            "brooks_concepts": ["FBO", "TR"],
            "ocr_text": "ocr",
            "analysis_text": "Short analysis.",
        },
    ]
    lines = [json.dumps(r) for r in records]
    p.write_text("\n".join(lines))
    return p


@pytest.fixture
def mock_vector_results() -> list[MagicMock]:
    """Mock Upstash Vector query results."""
    r1 = MagicMock()
    r1.metadata = {
        "page_number": 1,
        "pattern_type": "bull_flag",
        "direction": "long",
        "outcome": "success",
        "probability": "high",
        "always_in_direction": "AIL",
        "day_type": "trend",
        "brooks_concepts": ["AIL", "PB"],
        "gcs_jpg_url": "gs://bucket/brooks-charts/page_0001.jpg",
    }
    r1.score = 0.89

    r2 = MagicMock()
    r2.metadata = {
        "page_number": 5,
        "pattern_type": "FBO",
        "direction": "short",
        "outcome": "trap",
        "probability": "medium",
        "always_in_direction": "AIS",
        "day_type": "TR",
        "brooks_concepts": ["FBO", "TR"],
        "gcs_jpg_url": "gs://bucket/brooks-charts/page_0005.jpg",
    }
    r2.score = 0.72

    return [r1, r2]


class TestEmbedQueryContext:
    def test_calls_openai_with_correct_model(self) -> None:
        client = MagicMock()
        client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=[0.1] * 1536)]
        )

        embed_query_context(client, "test query")

        call_args = client.embeddings.create.call_args
        assert call_args[1]["model"] == "text-embedding-3-small"
        assert call_args[1]["input"] == "test query"


class TestRetrieveAnalogs:
    def test_returns_pydantic_models(
        self,
        mock_vector_results: list[MagicMock],
        enriched_jsonl: Path,
    ) -> None:
        vector_client = MagicMock()
        vector_client.query.return_value = mock_vector_results

        results = retrieve_analogs(
            vector_client, [0.1] * 1536, top_k=5,
            enriched_path=enriched_jsonl,
        )

        assert len(results) == 2
        assert all(isinstance(r, BrooksAnalog) for r in results)

    def test_respects_top_k(
        self,
        mock_vector_results: list[MagicMock],
        enriched_jsonl: Path,
    ) -> None:
        vector_client = MagicMock()
        vector_client.query.return_value = mock_vector_results[:1]

        results = retrieve_analogs(
            vector_client, [0.1] * 1536, top_k=1,
            enriched_path=enriched_jsonl,
        )

        vector_client.query.assert_called_once()
        call_args = vector_client.query.call_args
        assert call_args[1]["top_k"] == 1

    def test_includes_similarity_score(
        self,
        mock_vector_results: list[MagicMock],
        enriched_jsonl: Path,
    ) -> None:
        vector_client = MagicMock()
        vector_client.query.return_value = mock_vector_results

        results = retrieve_analogs(
            vector_client, [0.1] * 1536,
            enriched_path=enriched_jsonl,
        )

        assert results[0].similarity_score == 0.89
        assert results[1].similarity_score == 0.72

    def test_looks_up_analysis_summary(
        self,
        mock_vector_results: list[MagicMock],
        enriched_jsonl: Path,
    ) -> None:
        vector_client = MagicMock()
        vector_client.query.return_value = mock_vector_results

        results = retrieve_analogs(
            vector_client, [0.1] * 1536,
            enriched_path=enriched_jsonl,
        )

        # Page 1 has 500 chars of 'A', truncated to 400
        assert results[0].analysis_summary == "A" * 400
        # Page 5 has short analysis
        assert results[1].analysis_summary == "Short analysis."


class TestLoadAnalysisCache:
    def test_loads_from_jsonl(self, enriched_jsonl: Path) -> None:
        _load_analysis_cache(enriched_jsonl)

        assert 1 in _analysis_cache
        assert 5 in _analysis_cache
        assert len(_analysis_cache[1]) == 400  # truncated to 400

    def test_no_op_on_second_call(self, enriched_jsonl: Path) -> None:
        _load_analysis_cache(enriched_jsonl)
        count = len(_analysis_cache)
        _load_analysis_cache(enriched_jsonl)
        assert len(_analysis_cache) == count

    def test_handles_missing_file(self, tmp_path: Path) -> None:
        _load_analysis_cache(tmp_path / "nonexistent.jsonl")
        assert len(_analysis_cache) == 0

    def test_strips_boilerplate_and_truncates(self, tmp_path: Path) -> None:
        """Confirm Gemma header boilerplate is stripped before truncation."""
        p = tmp_path / "boilerplate.jsonl"
        raw_analysis = (
            "<!-- Page 3439 Analysis | Source: page_3439.jpg "
            "| Model: gemma-4-31b-it -->\n\n"
            "# Page 3439 — Deep Analysis\n\n"
            "## Macro Context\n"
            "The overall market structure is a **Strong Bull Trend** "
            "originating from the open. Price broke above the "
            "previous day's high within the first 15 minutes, "
            "establishing a bull trend from the open pattern. "
            "The always-in direction is long. "
            "EMA-20 slope is strongly positive. "
            "VWAP held as support on the first pullback. "
            "This is a classic Brooks trend day setup."
        )
        record = {
            "page_number": 3439,
            "source_jpg": "page_3439.jpg",
            "pattern_type": "bull_trend",
            "direction": "long",
            "probability": "high",
            "outcome": "success",
            "always_in_direction": "AIL",
            "day_type": "trend",
            "key_levels": [],
            "brooks_concepts": ["AIL"],
            "ocr_text": "ocr",
            "analysis_text": raw_analysis,
        }
        p.write_text(json.dumps(record))

        _load_analysis_cache(p)

        cached = _analysis_cache[3439]
        # Boilerplate stripped
        assert "<!--" not in cached
        assert "# Page 3439" not in cached
        assert "## Macro Context" not in cached
        # Actual content preserved
        assert cached.startswith("The overall market structure")
        # Length capped at 400
        assert len(cached) <= 400


class TestStripBoilerplate:
    def test_strips_html_comments(self) -> None:
        text = "<!-- comment -->Real content"
        assert _strip_boilerplate(text) == "Real content"

    def test_strips_markdown_headers(self) -> None:
        text = "# Title\n## Subtitle\nActual text"
        result = _strip_boilerplate(text)
        assert "# Title" not in result
        assert "## Subtitle" not in result
        assert "Actual text" in result

    def test_strips_multiline_comment(self) -> None:
        text = "<!-- multi\nline\ncomment -->Content"
        assert _strip_boilerplate(text) == "Content"

    def test_collapses_blank_lines(self) -> None:
        text = "<!-- removed -->\n\n\n\nContent here"
        assert _strip_boilerplate(text) == "Content here"

    def test_preserves_content_without_boilerplate(self) -> None:
        text = "Clean text with no boilerplate."
        assert _strip_boilerplate(text) == "Clean text with no boilerplate."

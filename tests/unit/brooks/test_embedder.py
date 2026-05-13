"""Unit tests for Brooks embedder module."""

import json
from unittest.mock import MagicMock, patch

import pytest
from openai import RateLimitError

from mirofish_forecast.brooks.embedder import (
    _GCS_BUCKET,
    _GCS_PREFIX,
    _MAX_CHARS,
    build_embedding_text,
    embed_text,
    index_page,
)
from mirofish_forecast.models.brooks import BrooksEnrichedPage


@pytest.fixture
def sample_enriched_page() -> BrooksEnrichedPage:
    """A sample enriched page for testing."""
    return BrooksEnrichedPage(
        page_number=42,
        source_jpg="page_042.jpg",
        pattern_type="wedge_top",
        direction="short",
        probability="high",
        outcome="success",
        always_in_direction="AIS",
        day_type="trend",
        key_levels=[2.067, 2.050],
        brooks_concepts=["AIS", "FBO", "LH", "PB", "EMA"],
        ocr_text="[CHART: wedge pattern]",
        analysis_text="The market forms a wedge top with three pushes.",
    )


class TestBuildEmbeddingText:
    def test_contains_structured_fields(
        self, sample_enriched_page: BrooksEnrichedPage
    ) -> None:
        text = build_embedding_text(sample_enriched_page)
        assert "Pattern: wedge_top" in text
        assert "Direction: short" in text
        assert "Outcome: success" in text
        assert "Probability: high" in text
        assert "Day Type: trend" in text
        assert "Always-In: AIS" in text

    def test_contains_concepts(
        self, sample_enriched_page: BrooksEnrichedPage
    ) -> None:
        text = build_embedding_text(sample_enriched_page)
        assert "AIS, FBO, LH, PB, EMA" in text

    def test_contains_analysis(
        self, sample_enriched_page: BrooksEnrichedPage
    ) -> None:
        text = build_embedding_text(sample_enriched_page)
        assert "Analysis:" in text
        assert "wedge top with three pushes" in text

    def test_truncates_oversized_text(
        self, sample_enriched_page: BrooksEnrichedPage
    ) -> None:
        # Create page with very long analysis
        long_page = BrooksEnrichedPage(
            page_number=99,
            source_jpg="page_099.jpg",
            pattern_type="test",
            direction="long",
            probability="high",
            outcome="success",
            always_in_direction="AIL",
            day_type="trend",
            key_levels=[],
            brooks_concepts=["AIL"],
            ocr_text="ocr",
            analysis_text="x" * 50_000,
        )
        text = build_embedding_text(long_page)
        assert len(text) <= _MAX_CHARS
        # Structured fields still present
        assert "Pattern: test" in text
        assert "Direction: long" in text


class TestEmbedText:
    def test_returns_embedding(self) -> None:
        client = MagicMock()
        mock_embedding = [0.1] * 1536
        client.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=mock_embedding)]
        )
        result = embed_text(client, "test text")
        assert result == mock_embedding
        assert len(result) == 1536

    @patch("mirofish_forecast.brooks.embedder.time.sleep")
    def test_retries_on_rate_limit(self, mock_sleep: MagicMock) -> None:
        client = MagicMock()
        mock_embedding = [0.1] * 1536

        # Fail first, succeed second
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        rate_error = RateLimitError(
            message="Rate limit",
            response=mock_response,
            body=None,
        )
        client.embeddings.create.side_effect = [
            rate_error,
            MagicMock(data=[MagicMock(embedding=mock_embedding)]),
        ]

        result = embed_text(client, "test text")
        assert result == mock_embedding
        assert client.embeddings.create.call_count == 2

    @patch("mirofish_forecast.brooks.embedder.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep: MagicMock) -> None:
        client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        client.embeddings.create.side_effect = RateLimitError(
            message="Rate limit",
            response=mock_response,
            body=None,
        )

        with pytest.raises(RuntimeError, match="failed after 3 retries"):
            embed_text(client, "test text")


class TestIndexPage:
    def test_constructs_metadata_correctly(
        self, sample_enriched_page: BrooksEnrichedPage
    ) -> None:
        vector_client = MagicMock()
        embedding = [0.1] * 1536

        index_page(vector_client, sample_enriched_page, embedding)

        call_args = vector_client.upsert.call_args
        vectors = call_args[1]["vectors"] if "vectors" in call_args[1] else call_args[0][0]
        # Handle both positional and keyword
        if isinstance(vectors, dict):
            vectors = [vectors]
        vec = vectors[0] if isinstance(vectors, list) else vectors

        assert vec["id"] == "page_0042"
        assert vec["metadata"]["page_number"] == 42
        assert vec["metadata"]["pattern_type"] == "wedge_top"
        assert vec["metadata"]["direction"] == "short"

    def test_gcs_url_format(
        self, sample_enriched_page: BrooksEnrichedPage
    ) -> None:
        vector_client = MagicMock()
        embedding = [0.1] * 1536

        index_page(vector_client, sample_enriched_page, embedding)

        call_args = vector_client.upsert.call_args
        vectors = call_args[1]["vectors"] if "vectors" in call_args[1] else call_args[0][0]
        if isinstance(vectors, dict):
            vectors = [vectors]
        meta = vectors[0]["metadata"]

        expected_url = f"gs://{_GCS_BUCKET}/{_GCS_PREFIX}/page_0042.jpg"
        assert meta["gcs_jpg_url"] == expected_url

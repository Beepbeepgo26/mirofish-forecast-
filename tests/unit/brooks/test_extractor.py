"""Unit tests for Brooks metadata extractor."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mirofish_forecast.brooks.extractor import (
    _EXTRACTION_PROMPT,
    extract_batch,
    extract_metadata,
    load_already_done,
)
from mirofish_forecast.models.brooks import BrooksEnrichedPage, BrooksPage


# --- Fixtures ---


@pytest.fixture
def sample_page() -> BrooksPage:
    """A sample BrooksPage for testing."""
    return BrooksPage(
        page_number=42,
        source_jpg="page_042.jpg",
        analysis_filename="page_0042_analysis.md",
        ocr_text="[CHART: A wedge pattern forming at the top.]",
        analysis_text=(
            "## Macro Context\n"
            "The market is AIS. A wedge top forms with three pushes.\n"
            "## Pattern Identification\n"
            "Wedge top with FBO above the upper channel line.\n"
            "## Key Takeaway\n"
            "High probability short entry on LH PB after the wedge completes."
        ),
        is_chart_page=True,
    )


@pytest.fixture
def valid_gemini_response() -> dict:
    """A valid Gemini JSON response."""
    return {
        "pattern_type": "wedge_top",
        "direction": "short",
        "probability": "high",
        "outcome": "success",
        "always_in_direction": "AIS",
        "day_type": "trend",
        "key_levels": [],
        "brooks_concepts": ["AIS", "FBO", "LH", "PB"],
    }


# --- extract_metadata ---


class TestExtractMetadata:
    @patch("mirofish_forecast.brooks.extractor.genai")
    def test_successful_extraction(
        self,
        mock_genai: MagicMock,
        sample_page: BrooksPage,
        valid_gemini_response: dict,
    ) -> None:
        model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_gemini_response)
        model.generate_content.return_value = response

        result = extract_metadata(model, sample_page)

        assert result is not None
        assert isinstance(result, BrooksEnrichedPage)
        assert result.page_number == 42
        assert result.pattern_type == "wedge_top"
        assert result.direction == "short"
        assert result.probability == "high"
        assert result.outcome == "success"
        assert result.always_in_direction == "AIS"
        assert result.day_type == "trend"
        assert "FBO" in result.brooks_concepts
        assert result.ocr_text == sample_page.ocr_text
        assert result.analysis_text == sample_page.analysis_text

    @patch("mirofish_forecast.brooks.extractor.genai")
    def test_json_parse_error_returns_none(
        self,
        mock_genai: MagicMock,
        sample_page: BrooksPage,
    ) -> None:
        model = MagicMock()
        response = MagicMock()
        response.text = "not valid json {{{}"
        model.generate_content.return_value = response

        result = extract_metadata(model, sample_page)
        assert result is None

    @patch("mirofish_forecast.brooks.extractor.genai")
    def test_api_exception_returns_none(
        self,
        mock_genai: MagicMock,
        sample_page: BrooksPage,
    ) -> None:
        model = MagicMock()
        model.generate_content.side_effect = Exception("Rate limit exceeded")

        result = extract_metadata(model, sample_page)
        assert result is None

    @patch("mirofish_forecast.brooks.extractor.genai")
    def test_missing_fields_use_defaults(
        self,
        mock_genai: MagicMock,
        sample_page: BrooksPage,
    ) -> None:
        model = MagicMock()
        response = MagicMock()
        # Minimal response — missing most fields
        response.text = json.dumps({
            "pattern_type": "bull_flag",
            "direction": "long",
        })
        model.generate_content.return_value = response

        result = extract_metadata(model, sample_page)

        assert result is not None
        assert result.pattern_type == "bull_flag"
        assert result.direction == "long"
        assert result.probability == "medium"  # default
        assert result.outcome == "unclear"  # default
        assert result.always_in_direction == "neutral"  # default
        assert result.day_type == "mixed"  # default
        assert result.key_levels == []  # default
        assert result.brooks_concepts == []  # default

    @patch("mirofish_forecast.brooks.extractor.genai")
    def test_prompt_uses_analysis_text(
        self,
        mock_genai: MagicMock,
        sample_page: BrooksPage,
        valid_gemini_response: dict,
    ) -> None:
        model = MagicMock()
        response = MagicMock()
        response.text = json.dumps(valid_gemini_response)
        model.generate_content.return_value = response

        extract_metadata(model, sample_page)

        # Verify the prompt contains the analysis text
        call_args = model.generate_content.call_args
        prompt = call_args[0][0]
        assert sample_page.analysis_text in prompt


# --- load_already_done ---


class TestLoadAlreadyDone:
    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        result = load_already_done(p)
        assert result == set()

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        p = tmp_path / "missing.jsonl"
        result = load_already_done(p)
        assert result == set()

    def test_loads_page_numbers(self, tmp_path: Path) -> None:
        p = tmp_path / "output.jsonl"
        lines = [
            json.dumps({"page_number": 1, "pattern_type": "x"}),
            json.dumps({"page_number": 5, "pattern_type": "y"}),
            json.dumps({"page_number": 10, "pattern_type": "z"}),
        ]
        p.write_text("\n".join(lines))

        result = load_already_done(p)
        assert result == {1, 5, 10}

    def test_handles_malformed_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "output.jsonl"
        content = (
            json.dumps({"page_number": 1}) + "\n"
            + "not json\n"
            + json.dumps({"page_number": 3}) + "\n"
        )
        p.write_text(content)

        result = load_already_done(p)
        assert result == {1, 3}


# --- extract_batch ---


class TestExtractBatch:
    @patch("mirofish_forecast.brooks.extractor.time.sleep")
    @patch("mirofish_forecast.brooks.extractor.extract_metadata")
    def test_skips_already_done(
        self,
        mock_extract: MagicMock,
        mock_sleep: MagicMock,
        sample_page: BrooksPage,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "out.jsonl"
        model = MagicMock()

        result = extract_batch(
            model=model,
            pages=[sample_page],
            output_path=output,
            already_done={42},  # sample_page.page_number
        )

        assert len(result) == 0
        mock_extract.assert_not_called()

    @patch("mirofish_forecast.brooks.extractor.time.sleep")
    @patch("mirofish_forecast.brooks.extractor.extract_metadata")
    def test_writes_to_output(
        self,
        mock_extract: MagicMock,
        mock_sleep: MagicMock,
        sample_page: BrooksPage,
        valid_gemini_response: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "out.jsonl"
        model = MagicMock()

        enriched = BrooksEnrichedPage(
            page_number=42,
            source_jpg="page_042.jpg",
            ocr_text="ocr",
            analysis_text="analysis",
            **valid_gemini_response,
        )
        mock_extract.return_value = enriched

        result = extract_batch(
            model=model,
            pages=[sample_page],
            output_path=output,
        )

        assert len(result) == 1
        assert output.exists()
        line = output.read_text().strip()
        data = json.loads(line)
        assert data["page_number"] == 42
        assert data["pattern_type"] == "wedge_top"

    @patch("mirofish_forecast.brooks.extractor.time.sleep")
    @patch("mirofish_forecast.brooks.extractor.extract_metadata")
    def test_retries_on_failure(
        self,
        mock_extract: MagicMock,
        mock_sleep: MagicMock,
        sample_page: BrooksPage,
        valid_gemini_response: dict,
        tmp_path: Path,
    ) -> None:
        output = tmp_path / "out.jsonl"
        model = MagicMock()

        enriched = BrooksEnrichedPage(
            page_number=42,
            source_jpg="page_042.jpg",
            ocr_text="ocr",
            analysis_text="analysis",
            **valid_gemini_response,
        )
        # Fail first attempt, succeed on second
        mock_extract.side_effect = [None, enriched]

        result = extract_batch(
            model=model,
            pages=[sample_page],
            output_path=output,
            max_retries=3,
        )

        assert len(result) == 1
        assert mock_extract.call_count == 2


# --- Prompt Quality ---


class TestPromptContent:
    def test_prompt_has_all_fields(self) -> None:
        """Verify the extraction prompt mentions all required output fields."""
        for field in [
            "pattern_type",
            "direction",
            "probability",
            "outcome",
            "always_in_direction",
            "day_type",
            "key_levels",
            "brooks_concepts",
        ]:
            assert field in _EXTRACTION_PROMPT

    def test_prompt_has_examples(self) -> None:
        """Verify the prompt includes concrete Brooks concept examples."""
        for concept in ["FBO", "MTR", "BLSHS", "AIS", "AIL"]:
            assert concept in _EXTRACTION_PROMPT

"""Unit tests for Brooks corpus parser."""

import json
import tempfile
from pathlib import Path

import pytest

from mirofish_forecast.brooks.parser import (
    is_chart_page,
    normalize_analysis_filename,
    normalize_jpg_filename,
    parse_corpus,
)
from mirofish_forecast.models.brooks import BrooksPage


# --- Test Fixtures ---

SAMPLE_CORPUS = """\
# Al Brooks Encyclopedia — Training Data (COMPLETE)

---

## Page 1 — OCR

<!-- Source: Encyclopedia_Part 1-16_Pg1.jpg | Page: 1 -->

# Classifications: A to B

The Brooks Encyclopedia of Chart Patterns

[CHART: A price chart showing candlestick patterns.]

## Page 1 — Analysis

<!-- Page 1 Analysis | Source: page_001.jpg | Model: gemma-4-31b-it -->

# Page 1 — Deep Analysis

This is a title/outline slide. There is no chart provided for technical analysis.

## Macro Context
N/A (Title Slide)

## Page 2 — OCR

<!-- Source: Encyclopedia_Part 1-16_Pg2.jpg | Page: 2 -->

Price action showing a strong bull trend with consecutive closes above EMA.

[CHART: A clear uptrend with higher highs and higher lows.]

## Page 2 — Analysis

<!-- Page 2 Analysis | Source: page_002.jpg | Model: gemma-4-31b-it -->

# Page 2 — Deep Analysis

## Macro Context
*   **Overall Market Structure:** Strong bull trend with price consistently above the EMA.
*   **Always In Direction:** AIL (Always In Long) throughout the sequence.

## Pattern Identification
*   **Bull Channel (Bars 10-50):** Consecutive higher highs and higher lows forming a well-defined channel.

## Signal Bar & Entry Analysis
*   **Bull BO Setup (Bar 25):** Signal bar is a strong bull trend bar closing on its high.

## Key Takeaway
Classic AIL environment with a clear channel pattern.

## Page 3 — OCR

<!-- Source: Encyclopedia_Part 1-16_Pg3.jpg | Page: 3 -->

Price action showing bear reversal.

## Page 3 — Analysis

<!-- Page 3 Analysis | Source: page_003.jpg | Model: gemma-4-31b-it -->

# Page 3 — Deep Analysis

This is a title slide introducing the section on bear reversals.

## Macro Context
N/A (Title Slide)

## Page 4 — OCR

<!-- Source: Encyclopedia_Part 1-16_Pg4.jpg | Page: 4 -->

Complex wedge top reversal pattern.

[CHART: A wedge pattern forming at the top of a bull trend.]

## Page 4 — Analysis

<!-- Page 4 Analysis | Source: page_004.jpg | Model: gemma-4-31b-it -->

# Page 4 — Deep Analysis

## Macro Context
*   **Overall Market Structure:** Transition from bull trend to potential reversal.
*   **Always In Direction:** AIS emerging.

## Pattern Identification
*   **Wedge Top (W):** Three pushes up forming a wedge reversal.
*   **FBO:** Failed breakout above the wedge.

## Signal Bar & Entry Analysis
*   **Bear reversal bar closing below midpoint.

## Key Takeaway
Wedge tops with FBO are high-probability reversal setups.

## Page 5 — OCR

<!-- Source: Encyclopedia_Part 1-16_Pg5.jpg | Page: 5 -->

Another chart page with channel analysis.

## Page 5 — Analysis

<!-- Page 5 Analysis | Source: page_005.jpg | Model: gemma-4-31b-it -->

# Page 5 — Deep Analysis

## Macro Context
*   **Overall Market Structure:** Bear channel with measured moves.

## Pattern Identification
*   **Bear Channel:** Lower highs and lower lows in a controlled decline.
"""


@pytest.fixture
def sample_corpus_path(tmp_path: Path) -> Path:
    """Write sample corpus to a temp file and return its path."""
    p = tmp_path / "combined_training_data.md"
    p.write_text(SAMPLE_CORPUS, encoding="utf-8")
    return p


# --- Filename Normalization ---


class TestNormalizeJpgFilename:
    def test_single_digit(self) -> None:
        assert normalize_jpg_filename(1) == "page_001.jpg"

    def test_double_digit(self) -> None:
        assert normalize_jpg_filename(42) == "page_042.jpg"

    def test_triple_digit(self) -> None:
        assert normalize_jpg_filename(999) == "page_999.jpg"

    def test_four_digit(self) -> None:
        assert normalize_jpg_filename(5780) == "page_5780.jpg"


class TestNormalizeAnalysisFilename:
    def test_single_digit(self) -> None:
        assert normalize_analysis_filename(1) == "page_0001_analysis.md"

    def test_four_digit(self) -> None:
        assert normalize_analysis_filename(5780) == "page_5780_analysis.md"


# --- Title Slide Detection ---


class TestIsChartPage:
    def test_chart_page(self) -> None:
        analysis = (
            "## Macro Context\n"
            "Strong bull trend with price above EMA.\n"
            "## Pattern Identification\n"
            "Bull Channel (Bars 10-50)."
        )
        assert is_chart_page(analysis) is True

    def test_title_slide(self) -> None:
        analysis = "This is a title/outline slide. There is no chart provided."
        assert is_chart_page(analysis) is False

    def test_na_title(self) -> None:
        analysis = "## Macro Context\nN/A (Title Slide)\n## Pattern Identification\nNone."
        assert is_chart_page(analysis) is False

    def test_outline_slide(self) -> None:
        analysis = "This page is an outline slide introducing the next section."
        assert is_chart_page(analysis) is False

    def test_no_chart_provided(self) -> None:
        analysis = "There is no chart provided for analysis in this page."
        assert is_chart_page(analysis) is False

    def test_this_is_a_title(self) -> None:
        analysis = "This is a title page for part 5 of the encyclopedia."
        assert is_chart_page(analysis) is False

    def test_empty_analysis_is_chart(self) -> None:
        """Empty analysis doesn't contain any markers, so it's treated as chart."""
        assert is_chart_page("") is True


# --- Corpus Parsing ---


class TestParseCorpus:
    def test_yields_all_pages(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        assert len(pages) == 5

    def test_page_numbers_in_order(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        numbers = [p.page_number for p in pages]
        assert numbers == [1, 2, 3, 4, 5]

    def test_title_slides_detected(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        chart_flags = {p.page_number: p.is_chart_page for p in pages}
        assert chart_flags[1] is False  # title slide
        assert chart_flags[2] is True  # chart page
        assert chart_flags[3] is False  # title slide
        assert chart_flags[4] is True  # chart page
        assert chart_flags[5] is True  # chart page

    def test_ocr_text_populated(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        page2 = pages[1]
        assert "strong bull trend" in page2.ocr_text

    def test_analysis_text_populated(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        page2 = pages[1]
        assert "Bull Channel" in page2.analysis_text
        assert "AIL" in page2.analysis_text

    def test_source_jpg_format(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        assert pages[0].source_jpg == "page_001.jpg"
        assert pages[3].source_jpg == "page_004.jpg"

    def test_analysis_filename_format(self, sample_corpus_path: Path) -> None:
        pages = list(parse_corpus(sample_corpus_path))
        assert pages[0].analysis_filename == "page_0001_analysis.md"
        assert pages[3].analysis_filename == "page_0004_analysis.md"

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.md"
        p.write_text("")
        pages = list(parse_corpus(p))
        assert pages == []


# --- Pydantic Validation ---


class TestBrooksPageValidation:
    def test_valid_record(self) -> None:
        page = BrooksPage(
            page_number=1,
            source_jpg="page_001.jpg",
            analysis_filename="page_0001_analysis.md",
            ocr_text="Some OCR text",
            analysis_text="Some analysis",
            is_chart_page=True,
        )
        assert page.page_number == 1

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(Exception):
            BrooksPage(
                page_number=1,
                source_jpg="page_001.jpg",
                analysis_filename="page_0001_analysis.md",
                ocr_text="text",
                analysis_text="text",
                is_chart_page=True,
                extra_field="not allowed",
            )

    def test_frozen_immutable(self) -> None:
        page = BrooksPage(
            page_number=1,
            source_jpg="page_001.jpg",
            analysis_filename="page_0001_analysis.md",
            ocr_text="text",
            analysis_text="text",
            is_chart_page=True,
        )
        with pytest.raises(Exception):
            page.page_number = 2  # type: ignore[misc]

    def test_serialization_roundtrip(self) -> None:
        page = BrooksPage(
            page_number=42,
            source_jpg="page_042.jpg",
            analysis_filename="page_0042_analysis.md",
            ocr_text="OCR content",
            analysis_text="Analysis content",
            is_chart_page=True,
        )
        data = json.loads(page.model_dump_json())
        restored = BrooksPage(**data)
        assert restored == page

"""Parser for the Brooks Encyclopedia combined training data markdown.

Splits the combined markdown by page headers, pairs OCR + Analysis
sections, filters title/outline slides, and yields BrooksPage records.
"""

import logging
import re
from collections.abc import Iterator
from pathlib import Path

from mirofish_forecast.models.brooks import BrooksPage

logger = logging.getLogger(__name__)

# Regex to match page section headers: "## Page 123 — OCR" or "## Page 123 — Analysis"
_PAGE_HEADER_RE = re.compile(r"^## Page (\d+) — (OCR|Analysis)$", re.MULTILINE)

# Substrings in analysis text that indicate a title/outline slide
_TITLE_SLIDE_MARKERS = (
    "title slide",
    "outline slide",
    "N/A (Title",
    "no chart provided",
    "This is a title",
)


def is_chart_page(analysis_text: str) -> bool:
    """Return True if the analysis describes a real chart, not a title slide.

    Checks the first ~500 characters of the analysis for title slide markers,
    since the classification typically appears in the opening paragraph.
    """
    prefix = analysis_text[:500].lower()
    return not any(marker.lower() in prefix for marker in _TITLE_SLIDE_MARKERS)


def normalize_jpg_filename(page_number: int) -> str:
    """Convert page number to 3-digit padded JPG filename.

    Args:
        page_number: The page number (1-based).

    Returns:
        Filename like "page_001.jpg".
    """
    return f"page_{page_number:03d}.jpg"


def normalize_analysis_filename(page_number: int) -> str:
    """Convert page number to 4-digit padded analysis filename.

    Args:
        page_number: The page number (1-based).

    Returns:
        Filename like "page_0001_analysis.md".
    """
    return f"page_{page_number:04d}_analysis.md"


def parse_corpus(input_path: Path) -> Iterator[BrooksPage]:
    """Parse the combined training data markdown into BrooksPage records.

    Splits by ``## Page N — OCR`` / ``## Page N — Analysis`` headers,
    pairs them, and yields one BrooksPage per page.

    Args:
        input_path: Path to combined_training_data.md.

    Yields:
        BrooksPage for each page in the corpus.
    """
    logger.info(f"Reading {input_path} ({input_path.stat().st_size / 1_000_000:.1f} MB)...")
    text = input_path.read_text(encoding="utf-8")

    # Find all header positions
    matches = list(_PAGE_HEADER_RE.finditer(text))
    if not matches:
        logger.warning("No page headers found in input file")
        return

    logger.info(f"Found {len(matches)} section headers")

    # Build a map: (page_number, section_type) -> content
    sections: dict[tuple[int, str], str] = {}

    for i, match in enumerate(matches):
        page_num = int(match.group(1))
        section_type = match.group(2)  # "OCR" or "Analysis"

        # Content runs from end of this header to start of next header (or EOF)
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()

        sections[(page_num, section_type)] = content

    # Collect unique page numbers in order
    page_numbers = sorted({pg for pg, _ in sections})

    for page_num in page_numbers:
        ocr = sections.get((page_num, "OCR"), "")
        analysis = sections.get((page_num, "Analysis"), "")

        if not ocr and not analysis:
            logger.warning(f"Page {page_num}: both OCR and Analysis are empty, skipping")
            continue

        chart = is_chart_page(analysis)

        yield BrooksPage(
            page_number=page_num,
            source_jpg=normalize_jpg_filename(page_num),
            analysis_filename=normalize_analysis_filename(page_num),
            ocr_text=ocr,
            analysis_text=analysis,
            is_chart_page=chart,
        )

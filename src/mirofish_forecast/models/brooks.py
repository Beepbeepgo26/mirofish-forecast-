"""Pydantic models for Brooks corpus data."""

from mirofish_forecast.models.base import MiroFishBaseModel


class BrooksPage(MiroFishBaseModel):
    """A single parsed page from the Brooks Encyclopedia.

    Represents the raw OCR text + analysis text pair for one page,
    with metadata for linking back to source files.
    """

    page_number: int
    source_jpg: str  # "page_001.jpg" (3-digit pad)
    analysis_filename: str  # "page_0001_analysis.md" (4-digit pad)
    ocr_text: str
    analysis_text: str
    is_chart_page: bool

"""Pydantic models for Brooks corpus data."""

from typing import Literal

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


class BrooksEnrichedPage(MiroFishBaseModel):
    """A Brooks page enriched with structured metadata from Gemini extraction.

    Contains the Gemini-extracted pattern classification, direction, outcome,
    and Brooks-specific concept tags alongside the original text fields.
    """

    page_number: int
    source_jpg: str
    pattern_type: str  # bull_flag, FBO, MTR, channel_break, etc.
    direction: Literal["long", "short", "neutral"]
    probability: Literal["high", "medium", "low"]
    outcome: Literal["success", "failure", "trap", "unclear"]
    always_in_direction: Literal["AIL", "AIS", "transition", "neutral"]
    day_type: Literal["TR", "trend", "channel", "mixed"]
    key_levels: list[float]
    brooks_concepts: list[str]  # AIS, MTR, BLSHS, FBO, etc.
    ocr_text: str
    analysis_text: str

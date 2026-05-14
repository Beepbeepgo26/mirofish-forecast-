"""Unit tests for Brooks prompt formatting."""

from mirofish_forecast.brooks.prompt_formatting import format_analogs_for_prompt
from mirofish_forecast.models.brooks import BrooksAnalog


def _make_analog(
    page: int = 1,
    score: float = 0.91,
    pattern_type: str = "bull_flag",
    direction: str = "long",
    outcome: str = "success",
    probability: str = "high",
    day_type: str = "trend",
    always_in: str = "AIL",
    concepts: list[str] | None = None,
    analysis: str = "Strong bull trend with pullback to EMA.",
) -> BrooksAnalog:
    return BrooksAnalog(
        page_number=page,
        pattern_type=pattern_type,
        direction=direction,
        outcome=outcome,
        probability=probability,
        always_in_direction=always_in,
        day_type=day_type,
        brooks_concepts=concepts or ["AIL", "PB", "EMA"],
        similarity_score=score,
        gcs_jpg_path="gs://bucket/page.jpg",
        analysis_summary=analysis,
    )


class TestFormatAnalogsForPrompt:
    def test_empty_list_returns_empty_string(self) -> None:
        result = format_analogs_for_prompt([])
        assert result == ""

    def test_single_analog_format(self) -> None:
        analog = _make_analog(page=42, score=0.9128)
        result = format_analogs_for_prompt([analog])

        assert "<historical_analogs>" in result
        assert "</historical_analogs>" in result
        assert "[Analog 1: similarity=0.91]" in result
        assert "Pattern: bull_flag" in result
        assert "Direction: long  |  Outcome: success  |  Probability: high" in result
        assert "Day Type: trend  |  Always-In: AIL" in result
        assert "Brooks Concepts: AIL, PB, EMA" in result
        assert "Analysis: Strong bull trend with pullback to EMA." in result

    def test_similarity_formatted_to_two_decimals(self) -> None:
        analog = _make_analog(score=0.9)
        result = format_analogs_for_prompt([analog])
        assert "similarity=0.90" in result

    def test_five_analogs_have_five_markers(self) -> None:
        analogs = [_make_analog(page=i, score=0.95 - i * 0.01) for i in range(5)]
        result = format_analogs_for_prompt(analogs)

        for i in range(1, 6):
            assert f"[Analog {i}:" in result

    def test_no_empty_block_on_empty_list(self) -> None:
        """Empty list should return '', not '<historical_analogs></historical_analogs>'."""
        result = format_analogs_for_prompt([])
        assert "<historical_analogs>" not in result
        assert result == ""

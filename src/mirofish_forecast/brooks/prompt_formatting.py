"""Format Brooks analogs for injection into agent CoT prompts."""

from mirofish_forecast.models.brooks import BrooksAnalog


def format_analogs_for_prompt(analogs: list[BrooksAnalog]) -> str:
    """Format a list of BrooksAnalog into the prompt injection block.

    Returns empty string if analogs is empty (zero footprint in prompt).

    Args:
        analogs: List of retrieved Brooks analogs.

    Returns:
        Formatted ``<historical_analogs>`` block, or ``""`` if empty.
    """
    if not analogs:
        return ""

    lines: list[str] = ["<historical_analogs>"]

    for i, analog in enumerate(analogs, 1):
        concepts = ", ".join(analog.brooks_concepts)
        lines.append(
            f"[Analog {i}: similarity={analog.similarity_score:.2f}]\n"
            f"Pattern: {analog.pattern_type}\n"
            f"Direction: {analog.direction}  |  Outcome: {analog.outcome}"
            f"  |  Probability: {analog.probability}\n"
            f"Day Type: {analog.day_type}  |  Always-In: "
            f"{analog.always_in_direction}\n"
            f"Brooks Concepts: {concepts}\n"
            f"Analysis: {analog.analysis_summary}"
        )

    lines.append("</historical_analogs>")
    return "\n".join(lines)

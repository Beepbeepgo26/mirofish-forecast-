"""Gemini 2.5 Flash extractor for structured Brooks metadata.

Calls Gemini for each parsed page, extracting pattern classification,
direction, outcome, and Brooks-specific concept tags. Includes rate
limiting and resumability for the free tier (15 req/min, 1500 req/day).
"""

import json
import logging
import time
from pathlib import Path

import google.generativeai as genai

from mirofish_forecast.models.brooks import BrooksEnrichedPage, BrooksPage

logger = logging.getLogger(__name__)

# Gemini free tier: 15 requests/minute
_MIN_REQUEST_INTERVAL_S = 4.1  # ~14.6 req/min, safe margin

_EXTRACTION_PROMPT = """\
You are a trading pattern classifier specializing in Al Brooks Price Action methodology.

Given the analysis text below from the Brooks Encyclopedia of Chart Patterns, extract the following structured metadata. Use ONLY the analysis text as your primary source. Do not infer beyond what is explicitly stated.

## Fields to Extract

1. **pattern_type** (string): The primary chart pattern identified. Use lowercase_snake_case. Examples: "wedge_top", "double_bottom", "bull_flag", "bear_channel", "FBO", "MTR", "spike_and_channel", "trading_range", "broad_channel", "ii_pattern", "outside_bar_reversal", "micro_double_bottom", "expanding_triangle", "final_flag", "parabolic_wedge". If multiple patterns, pick the most prominent one discussed.

2. **direction** (string): The primary trade direction discussed. One of: "long", "short", "neutral".

3. **probability** (string): The probability of the primary setup as described. One of: "high", "medium", "low".

4. **outcome** (string): Whether the described setup succeeded. One of: "success", "failure", "trap", "unclear".

5. **always_in_direction** (string): The Always In direction at the time of the pattern. One of: "AIL", "AIS", "transition", "neutral".

6. **day_type** (string): The market day type. One of: "TR" (trading range), "trend", "channel", "mixed".

7. **key_levels** (list of floats): Numeric price levels explicitly mentioned in the analysis. Return empty list if no specific prices are mentioned.

8. **brooks_concepts** (list of strings): Brooks-specific abbreviations and concepts referenced. Examples: "AIS", "AIL", "MTR", "FBO", "BO", "PB", "BLSHS", "TTR", "SX", "BX", "MAG", "HSB", "HST", "MDB", "MDT", "EMA", "LOD", "HOD", "FT", "W", "MM", "TR", "BTC". Extract ALL concepts mentioned.

## Analysis Text

{analysis_text}

## Response Format

Return ONLY valid JSON with exactly these keys: pattern_type, direction, probability, outcome, always_in_direction, day_type, key_levels, brooks_concepts.
"""


def configure_client(api_key: str) -> genai.GenerativeModel:
    """Configure the Gemini client and return a model instance.

    Args:
        api_key: Gemini API key from AI Studio.

    Returns:
        Configured GenerativeModel for extraction.
    """
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )


# Allowed values for Literal fields — maps field name to (allowed_set, default)
_FIELD_CONSTRAINTS: dict[str, tuple[set[str], str]] = {
    "direction": ({"long", "short", "neutral"}, "neutral"),
    "probability": ({"high", "medium", "low"}, "medium"),
    "outcome": ({"success", "failure", "trap", "unclear"}, "unclear"),
    "always_in_direction": ({"AIL", "AIS", "transition", "neutral"}, "neutral"),
    "day_type": ({"TR", "trend", "channel", "mixed"}, "mixed"),
}


def _normalize_field(field: str, value: str) -> str:
    """Clamp a Gemini-returned value to the allowed Literal set.

    Args:
        field: Field name.
        value: Raw value from Gemini.

    Returns:
        The value if valid, otherwise the field's default.
    """
    allowed, default = _FIELD_CONSTRAINTS.get(field, (set(), value))
    return value if value in allowed else default


def extract_metadata(
    model: genai.GenerativeModel,
    page: BrooksPage,
) -> BrooksEnrichedPage | None:
    """Extract structured metadata from a single Brooks page.

    Args:
        model: Configured Gemini model.
        page: Parsed BrooksPage record.

    Returns:
        BrooksEnrichedPage with extracted metadata, or None on failure.
    """
    prompt = _EXTRACTION_PROMPT.format(analysis_text=page.analysis_text)

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Parse JSON response
        data = json.loads(raw)

        # Normalize key_levels: filter non-numeric values
        raw_levels = data.get("key_levels", [])
        key_levels: list[float] = []
        for lv in raw_levels:
            try:
                key_levels.append(float(lv))
            except (ValueError, TypeError):
                continue

        return BrooksEnrichedPage(
            page_number=page.page_number,
            source_jpg=page.source_jpg,
            pattern_type=data.get("pattern_type", "unknown"),
            direction=_normalize_field("direction", data.get("direction", "neutral")),
            probability=_normalize_field("probability", data.get("probability", "medium")),
            outcome=_normalize_field("outcome", data.get("outcome", "unclear")),
            always_in_direction=_normalize_field(
                "always_in_direction", data.get("always_in_direction", "neutral")
            ),
            day_type=_normalize_field("day_type", data.get("day_type", "mixed")),
            key_levels=key_levels,
            brooks_concepts=data.get("brooks_concepts", []),
            ocr_text=page.ocr_text,
            analysis_text=page.analysis_text,
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Page {page.page_number}: JSON parse error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Page {page.page_number}: extraction failed: {e}")
        return None


def extract_batch(
    model: genai.GenerativeModel,
    pages: list[BrooksPage],
    output_path: Path,
    already_done: set[int] | None = None,
    max_retries: int = 3,
) -> list[BrooksEnrichedPage]:
    """Extract metadata for a batch of pages with rate limiting.

    Writes each successful extraction to output_path immediately for
    crash resilience. Skips pages in already_done set (resumability).

    Args:
        model: Configured Gemini model.
        pages: List of BrooksPage records to process.
        output_path: Path to append JSONL output.
        already_done: Set of page numbers already extracted.
        max_retries: Max retries per page on transient errors.

    Returns:
        List of successfully extracted BrooksEnrichedPage records.
    """
    if already_done is None:
        already_done = set()

    results: list[BrooksEnrichedPage] = []
    total = len(pages)
    skipped = 0

    for i, page in enumerate(pages, 1):
        if page.page_number in already_done:
            skipped += 1
            continue

        # Rate limiting
        time.sleep(_MIN_REQUEST_INTERVAL_S)

        enriched = None
        for attempt in range(1, max_retries + 1):
            enriched = extract_metadata(model, page)
            if enriched is not None:
                break

            # Exponential backoff on failure
            wait = _MIN_REQUEST_INTERVAL_S * (2**attempt)
            logger.warning(
                f"Page {page.page_number}: attempt {attempt}/{max_retries} "
                f"failed, retrying in {wait:.0f}s..."
            )
            time.sleep(wait)

        if enriched is not None:
            results.append(enriched)
            # Append immediately for crash resilience
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(enriched.model_dump(), ensure_ascii=False) + "\n")

            if (i - skipped) % 50 == 0 or i == total:
                logger.info(
                    f"Progress: {i - skipped}/{total - skipped} extracted ({skipped} skipped)"
                )
        else:
            logger.error(f"Page {page.page_number}: failed after {max_retries} attempts")

    logger.info(
        f"Batch complete: {len(results)} extracted, "
        f"{skipped} skipped, {total - len(results) - skipped} failed"
    )
    return results


def load_already_done(output_path: Path) -> set[int]:
    """Load page numbers already extracted from existing output file.

    Args:
        output_path: Path to the JSONL output file.

    Returns:
        Set of page numbers already in the output.
    """
    done: set[int] = set()
    if not output_path.exists():
        return done

    with open(output_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                done.add(data["page_number"])
            except (json.JSONDecodeError, KeyError):
                continue

    logger.info(f"Loaded {len(done)} already-extracted pages from {output_path}")
    return done
